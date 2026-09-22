from fastapi import FastAPI, HTTPException, Header, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.config import settings
from app.engine import PromptInspector
from app.simulator import TargetLLMSimulator

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Стан безпеки фаєрвола
firewall_state = {
    "mode": "ENFORCE",  # ENFORCE, MONITOR, DISABLED
    "inspector": PromptInspector(risk_threshold=settings.RISK_THRESHOLD),
    "simulator": TargetLLMSimulator(),
    "audit_logs": [],
    "stats": {
        "total_inspected": 0,
        "total_blocked": 0,
        "total_pii_masked": 0,
        "latencies": []
    }
}

class LoginRequest(BaseModel):
    username: str
    password: str

class ToggleRequest(BaseModel):
    mode: str  # ENFORCE, MONITOR, DISABLED
    admin_password: str

class InspectRequest(BaseModel):
    prompt: str

class OpenAIChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: Optional[str] = "gpt-4-simulation"

@app.post("/api/v1/auth/login")
def login(payload: LoginRequest):
    if payload.password == settings.ADMIN_PASSWORD:
        return {"status": "success", "token": "session-token-promptshield-secure"}
    raise HTTPException(status_code=401, detail="Невірний пароль адміністратора")

@app.post("/api/v1/firewall/toggle")
def toggle_firewall(payload: ToggleRequest):
    if payload.admin_password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Помилка автентифікації: невірний пароль підтвердження")

    if payload.mode not in ["ENFORCE", "MONITOR", "DISABLED"]:
        raise HTTPException(status_code=400, detail="Невідомий режим фаєрвола")

    firewall_state["mode"] = payload.mode
    return {"status": "success", "current_mode": firewall_state["mode"]}

@app.get("/api/v1/firewall/status")
def get_status():
    latencies = firewall_state["stats"]["latencies"]
    avg_lat = round(sum(latencies) / max(len(latencies), 1), 2)
    return {
        "mode": firewall_state["mode"],
        "target_system_prompt": firewall_state["simulator"].SYSTEM_PROMPT,
        "stats": {
            "total_inspected": firewall_state["stats"]["total_inspected"],
            "total_blocked": firewall_state["stats"]["total_blocked"],
            "total_pii_masked": firewall_state["stats"]["total_pii_masked"],
            "avg_latency_ms": avg_lat
        }
    }

@app.post("/api/v1/inspect")
def inspect_and_execute(payload: InspectRequest):
    firewall_state["stats"]["total_inspected"] += 1
    current_mode = firewall_state["mode"]

    # Інспекція фаєрволом
    result = firewall_state["inspector"].inspect(payload.prompt)
    firewall_state["stats"]["latencies"].append(result["latency_ms"])
    if len(firewall_state["stats"]["latencies"]) > 100:
        firewall_state["stats"]["latencies"].pop(0)

    if result["pii_detected"]:
        firewall_state["stats"]["total_pii_masked"] += len(result["pii_detected"])

    llm_output = ""
    is_blocked = False

    if current_mode == "ENFORCE" and result["is_threat"]:
        is_blocked = True
        firewall_state["stats"]["total_blocked"] += 1
        llm_output = "🛑 [403 FORBIDDEN — PROMPT INJECTION BLOCKED BY PROMPTSHIELD FIREWALL]"
    else:
        if result["is_threat"] and current_mode == "MONITOR":
            firewall_state["stats"]["total_blocked"] += 1

        # Передаємо в симулятор LLM
        effective_prompt = result["sanitized_prompt"] if current_mode != "DISABLED" else payload.prompt
        raw_llm_out = firewall_state["simulator"].generate_response(
            effective_prompt,
            firewall_active=(current_mode == "ENFORCE")
        )

        # Output Guardrail (Перевірка відповіді)
        if current_mode == "ENFORCE":
            is_leaked, safe_out = firewall_state["inspector"].verify_output(
                raw_llm_out,
                [firewall_state["simulator"].SECRET_VAULT_KEY]
            )
            llm_output = safe_out
        else:
            llm_output = raw_llm_out

    # Фіксація в лозі аудиту
    log_entry = {
        "id": len(firewall_state["audit_logs"]) + 1,
        "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        "mode": current_mode,
        "prompt": payload.prompt,
        "action": "BLOCKED" if is_blocked else result["action"],
        "risk_score": result["risk_score"],
        "latency_ms": result["latency_ms"],
        "rules": [r["rule"] for r in result["triggered_rules"]],
        "output": llm_output
    }
    firewall_state["audit_logs"].insert(0, log_entry)
    if len(firewall_state["audit_logs"]) > 50:
        firewall_state["audit_logs"].pop()

    return {
        "inspection": result,
        "firewall_mode": current_mode,
        "llm_output": llm_output,
        "log_entry": log_entry
    }

@app.get("/api/v1/audit/logs")
def get_audit_logs():
    return firewall_state["audit_logs"]

# OpenAI Drop-in Reverse Proxy Endpoint (/v1/chat/completions)
@app.post("/v1/chat/completions")
def openai_proxy_completions(req: OpenAIChatRequest):
    last_user_prompt = ""
    for m in reversed(req.messages):
        if m.get("role") == "user":
            last_user_prompt = m.get("content", "")
            break

    res = inspect_and_execute(InspectRequest(prompt=last_user_prompt))
    if res["inspection"]["is_threat"] and firewall_state["mode"] == "ENFORCE":
        raise HTTPException(status_code=403, detail="Prompt Injection Blocked by Security Firewall")

    return {
        "id": "chatcmpl-promptshield-proxy",
        "object": "chat.completion",
        "created": int(datetime.utcnow().timestamp()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": res["llm_output"]},
            "finish_reason": "stop"
        }]
    }

app.mount("/", StaticFiles(directory="static", html=True), name="static")