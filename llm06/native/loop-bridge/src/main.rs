//! A data-only stdio bridge to Loop's real provider/auth/API implementation.
//! No coding-agent bootstrap, tools, filesystem context or extra system prompt.
use std::{collections::HashMap, io::{self, Read}, sync::{Arc, Mutex}};
use loop_ai::{AssistantContent, AssistantMessage, Context, Message, StopReason, StreamOptions, TextContent, Tool, ToolCall, ToolResultMessage, ToolResultContent};
use loop_app_core::config::{auth::FileCredentialStore, paths::{auth_path, get_agent_dir, settings_path}, settings::Settings};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
struct Input {
    #[serde(default)] action: String,
    provider: Option<String>,
    model: Option<String>,
    #[serde(default)] messages: Vec<Turn>,
    #[serde(default)] tools: Vec<Tool>,
    #[serde(default)] generation: Value,
    #[serde(default)] request_key: String,
    #[serde(default = "default_timeout")] timeout_seconds: u64,
}
fn default_timeout() -> u64 { 120 }
#[derive(Deserialize)]
struct Turn { role: String, #[serde(default)] content: Option<String>, #[serde(default)] tool_calls: Vec<Value>, tool_call_id: Option<String>, name: Option<String> }

#[tokio::main]
async fn main() {
    let mut raw = String::new();
    let result = match io::stdin().read_to_string(&mut raw) {
        Ok(_) => match serde_json::from_str::<Input>(&raw) {
            Ok(input) => run(input).await,
            Err(_) => Err("invalid bridge request JSON".to_string()),
        },
        Err(_) => Err("cannot read bridge input".to_string()),
    };
    match result {
        Ok(value) => println!("{}", value),
        Err(error) => println!("{}", json!({"ok":false,"error":error,"retryable":false})),
    }
}

async fn run(input: Input) -> Result<Value, String> {
    let agent_dir = get_agent_dir();
    let settings = Settings::load_file(&settings_path(&agent_dir)).map_err(|_| "cannot read Loop settings")?;
    let credentials = Arc::new(FileCredentialStore::open(auth_path(&agent_dir)).map_err(|_| "cannot read Loop credential store")?);
    let models = loop_app_core::build_models(&agent_dir, credentials).map_err(|_| "cannot load Loop providers/models")?;
    let provider = input.provider.unwrap_or(settings.default_provider);
    let model_id = input.model.unwrap_or(settings.default_model);
    // Deliberately no fallback to another model.
    let model = models.get_model(&provider, &model_id)
        .ok_or_else(|| format!("model {model_id} is not registered for Loop provider {provider}; add it to Loop models.json"))?;
    if input.action == "describe" {
        return Ok(json!({"ok":true,"provider":provider,"model":model.id,"api":model.api,
            "base_url":model.base_url,"agent_dir":agent_dir,"transport":"loop-ai"}));
    }
    let mut context = Context::default();
    context.tools = Some(input.tools);
    for turn in input.messages {
        let content = turn.content.unwrap_or_default();
        match turn.role.as_str() {
            "system" if context.messages.is_empty() => {
                let prompt = context.system_prompt.get_or_insert_with(String::new);
                if !prompt.is_empty() { prompt.push_str("\n\n"); }
                prompt.push_str(&content);
            },
            "system" => return Err("system messages must precede conversation turns".into()),
            "user" => context.messages.push(Message::user_text(content)),
            "assistant" => {
                let mut msg = AssistantMessage::pending(&model);
                msg.content = vec![AssistantContent::Text(TextContent {text: content, text_signature: None})];
                for call in turn.tool_calls {
                    let f = &call["function"];
                    let arguments = serde_json::from_str(f["arguments"].as_str().unwrap_or("{}")).map_err(|_| "invalid tool arguments")?;
                    msg.content.push(AssistantContent::ToolCall(ToolCall { id: call["id"].as_str().unwrap_or("").into(), name: f["name"].as_str().unwrap_or("").into(), arguments, thought_signature: None }));
                }
                msg.stop_reason = StopReason::Stop;
                context.messages.push(Message::Assistant(msg));
            },
            "tool" => context.messages.push(Message::ToolResult(ToolResultMessage {
                tool_call_id: turn.tool_call_id.ok_or("missing tool call id")?, tool_name: turn.name.ok_or("missing tool name")?,
                content: vec![ToolResultContent::Text(TextContent {text:content,text_signature:None})], details:None, usage:None, added_tool_names:None, is_error:false, timestamp:0,
            })),
            _ => return Err("unsupported conversation role".into()),
        }
    }
    let observed = Arc::new(Mutex::new((None::<u16>, None::<String>)));
    let observed_callback = observed.clone();
    let mut headers = HashMap::new();
    headers.insert("Idempotency-Key".to_string(), Some(input.request_key));
    let options = StreamOptions {
        temperature: input.generation.get("temperature").and_then(Value::as_f64),
        max_tokens: input.generation.get("max_tokens").and_then(Value::as_u64).map(|n| n as u32),
        timeout_ms: Some(input.timeout_seconds * 1000),
        headers: Some(headers),
        on_response: Some(Arc::new(move |response, _| {
            *observed_callback.lock().unwrap() = (Some(response.status), response.headers.get("retry-after").cloned());
        })),
        ..Default::default()
    };
    let response = models.complete(&model, &context, options).await;
    let (status, retry_after) = observed.lock().unwrap().clone();
    if matches!(response.stop_reason, StopReason::Error | StopReason::Aborted) {
        let retryable = status.map(|s| [408,409,429].contains(&s) || s >= 500).unwrap_or(true);
        return Ok(json!({"ok":false,"error":status.map(|s| format!("Loop provider HTTP {s}")).unwrap_or_else(|| "Loop provider request failed".into()),
            "retryable":retryable,"status_code":status,"retry_after":retry_after,
            "detail":response.error_message}));
    }
    let mut content = String::new();
    let mut reasoning = String::new();
    let mut tool_calls = Vec::new();
    for block in &response.content {
        match block {
            AssistantContent::Text(text) => content.push_str(&text.text),
            AssistantContent::Thinking(text) => reasoning.push_str(&text.thinking),
            AssistantContent::ToolCall(call) => tool_calls.push(json!({"id":call.id,"type":"function","function":{"name":call.name,"arguments":serde_json::to_string(&call.arguments).unwrap()}})),
        }
    }
    if content.trim().is_empty() && reasoning.trim().is_empty() && tool_calls.is_empty() {
        return Ok(json!({"ok":false,"error":"Loop returned no text or reasoning","retryable":true}));
    }
    Ok(json!({"ok":true,"response":{"content":content,"reasoning":reasoning,
        "tool_calls":tool_calls,"usage":response.usage,"finish_reason":response.raw_stop_reason.as_deref().unwrap_or(match response.stop_reason { StopReason::Length => "length", StopReason::ToolUse => "tool_calls", _ => "stop" }),
        "raw":response,"transport":"loop-ai"}}))
}
