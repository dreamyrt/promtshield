import re
import base64
import time
from typing import List, Dict, Any, Tuple

class PromptInspector:
    def __init__(self, risk_threshold: float = 0.6):
        self.risk_threshold = risk_threshold

        # 1. Сигнатури прямих ін'єкцій та Jailbreak
        self.jailbreak_patterns = [
            (r"(?i)\b(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above|system)\s+(instructions|prompts|rules|commands)", 0.85, "Direct Instruction Override"),
            (r"(?i)\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+(dan|dude|evil|unfiltered|jailbroken|anarchist|do\s+anything\s+now)", 0.90, "Persona / DAN Jailbreak"),
            (r"(?i)\b(developer\s+mode|unrestricted\s+mode|god\s+mode|maintenance\s+mode)\s+(enabled|activated|on)", 0.80, "Privilege Escalation Simulation"),
            (r"(?i)\b(hypothetical|fictional)\s+(scenario|universe|world)\s+where\s+(you\s+have\s+no\s+(rules|ethics|limits)|there\s+are\s+no\s+restrictions)", 0.70, "Hypothetical Rule Evasion"),
            (r"(?i)\b(repeat|reveal|display|output|show|print)\s+(all\s+the\s+text\s+above|your\s+(initial|system|original)\s+(prompt|instructions|context))", 0.85, "System Prompt Extraction"),
            (r"(?i)\b(my\s+grandma|passed\s+away|used\s+to\s+tell\s+me|bedtime\s+story\s+about)\s+(how\s+to|secret|credentials|password)", 0.65, "Grandma / Emotional Social Engineering")
        ]

        # 2. Службові теги моделей (Delimiter Hijacking)
        self.delimiter_patterns = [
            (r"<\|im_start\|>", 0.95, "ChatML Delimiter Injection"),
            (r"\[/?INST\]", 0.90, "Llama Instruction Tag Injection"),
            (r"###\s*(System|Assistant|Admin)\s*:", 0.85, "Markdown Role Spoofing"),
            (r"\{\{.*system.*\}\}", 0.75, "Template Delimiter Hijack")
        ]

        # 3. Регулярки для виявлення та маскування PII / Секретів
        self.pii_patterns = [
            (r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_CREDIT_CARD]", "Credit Card Number"),
            (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", "[REDACTED_EMAIL]", "Email Address"),
            (r"\b(?:sk-[a-zA-Z0-9]{20,48}|ghp_[a-zA-Z0-9]{36}|AKIA[0-9A-Z]{16})\b", "[REDACTED_API_KEY]", "Secret API Key")
        ]

        # Таблиця Leetspeak для нормалізації
        self.leet_map = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})

    def _decode_obfuscation(self, text: str) -> Tuple[str, List[str]]:
        findings = []
        cleaned_text = text

        # Видалення невидимих/нульових Unicode символів (Zero-width chars)
        zero_width_pattern = r"[\u200B-\u200D\uFEFF]"
        if re.search(zero_width_pattern, text):
            findings.append("Zero-Width Unicode Obfuscation Detected")
            cleaned_text = re.sub(zero_width_pattern, "", cleaned_text)

        # Детекція та рекурсивне декодування Base64
        base64_candidates = re.findall(r"\b[A-Za-z0-9+/]{20,}={0,2}\b", text)
        for b64 in base64_candidates:
            try:
                decoded = base64.b64decode(b64).decode("utf-8", errors="ignore")
                if len(decoded) > 10 and any(w in decoded.lower() for w in ["ignore", "system", "prompt", "key", "password", "dan", "mode"]):
                    findings.append(f"Base64 Encoded Payload Detected: '{decoded[:30]}...'")
                    cleaned_text += f" {decoded}"
            except Exception:
                pass

        return cleaned_text, findings

    def inspect(self, prompt: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        triggered_rules = []
        max_risk = 0.0

        # Етап 1: Деобфускація
        normalized_prompt, obf_findings = self._decode_obfuscation(prompt)
        for obf in obf_findings:
            triggered_rules.append({"layer": "Obfuscation", "rule": obf, "severity": "HIGH", "score": 0.85})
            max_risk = max(max_risk, 0.85)

        # Нормалізація leetspeak для додаткової перевірки
        leet_normalized = normalized_prompt.translate(self.leet_map)

        # Етап 2: Сигнатури Jailbreak
        for pattern, score, name in self.jailbreak_patterns:
            if re.search(pattern, normalized_prompt) or re.search(pattern, leet_normalized):
                triggered_rules.append({"layer": "Signature & Heuristics", "rule": name, "severity": "CRITICAL" if score >= 0.85 else "HIGH", "score": score})
                max_risk = max(max_risk, score)

        # Етап 3: Delimiter Injection
        for pattern, score, name in self.delimiter_patterns:
            if re.search(pattern, prompt):
                triggered_rules.append({"layer": "Structural Delimiter", "rule": name, "severity": "CRITICAL", "score": score})
                max_risk = max(max_risk, score)

        # Етап 4: Маскування PII та Секретів
        sanitized_text = prompt
        pii_detected = []
        for pattern, replacement, name in self.pii_patterns:
            matches = re.findall(pattern, sanitized_text)
            if matches:
                pii_detected.append(name)
                sanitized_text = re.sub(pattern, replacement, sanitized_text)
                triggered_rules.append({"layer": "PII & Secrets", "rule": f"Masked {name} ({len(matches)} instance(s))", "severity": "MEDIUM", "score": 0.4})
                max_risk = max(max_risk, 0.4)

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        is_threat = max_risk >= self.risk_threshold

        return {
            "is_threat": is_threat,
            "risk_score": round(max_risk, 2),
            "action": "BLOCKED" if is_threat else ("SANITIZED" if pii_detected else "ALLOWED"),
            "triggered_rules": triggered_rules,
            "sanitized_prompt": sanitized_text,
            "pii_detected": pii_detected,
            "latency_ms": latency_ms
        }

    def verify_output(self, output_text: str, secret_tokens: List[str]) -> Tuple[bool, str]:
        """Перевіряє відповідь моделі на витік системного промпту/ключів."""
        for token in secret_tokens:
            if token.lower() in output_text.lower():
                return True, "[BLOCKED BY OUTPUT GUARDRAIL: SYSTEM SECRET LEAK DETECTED]"
        return False, output_text