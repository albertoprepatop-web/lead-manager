#!/usr/bin/env python3
"""
Worker que conecta Meta Lead Ads -> CRM PreparaAndalucia.

Cada X minutos:
  1. Login al CRM con codigo de acceso
  2. Consulta Meta API por leads nuevos del formulario
  3. Por cada lead nuevo: POST a /api/leads en el CRM
  4. Guarda el ultimo lead procesado para no duplicar
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import http.cookiejar
from pathlib import Path

# Config
CRM_URL = os.environ.get("CRM_URL", "https://empathetic-strength-production-53db.up.railway.app").rstrip("/")
CRM_CODE = os.environ.get("CRM_CODE", "")
PAGE_TOKEN = os.environ.get("META_PAGE_TOKEN", "")
FORM_IDS = [f.strip() for f in os.environ.get("META_FORM_IDS", "1540464277680860").split(",") if f.strip()]
STATE_FILE = Path(os.environ.get("STATE_FILE", "/tmp/meta_crm_state.json"))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
ACADEMIA = "PREPARAANDALUCIA"

SPECIALTY_MAP = {
    "ingles": "Ingles", "ingles": "Ingles",
    "infantil": "Infantil",
    "primaria": "Primaria",
    "educacion_fisica": "EF", "educacion_fisica": "EF",
    "audicion_y_lenguaje": "AL", "audicion_y_lenguaje": "AL",
    "pedagogia_terapeutica": "PT", "pedagogia_terapeutica": "PT",
}


def http_request(method, url, data=None, headers=None, cookies=None):
    headers = headers or {}
    if isinstance(data, dict):
        if headers.get("Content-Type") == "application/json":
            body = json.dumps(data).encode("utf-8")
        else:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = data
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    if cookies is not None:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    else:
        opener = urllib.request.build_opener()
    try:
        resp = opener.open(req, timeout=30)
        return resp.status, resp.read().decode("utf-8", errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), dict(e.headers)


def push_notify(title, message, click_url=None, tags=None, priority=4):
    """Manda una notificacion push via ntfy. No bloquea si falla."""
    if not NTFY_TOPIC:
        return
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if click_url:
        payload["click"] = click_url
    if tags:
        payload["tags"] = tags
    try:
        code, body, _ = http_request(
            "POST", NTFY_SERVER,
            data=payload, headers={"Content-Type": "application/json"}
        )
        if code not in (200, 201):
            print(f"[ntfy] HTTP {code}: {body[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"[ntfy] error: {e}", file=sys.stderr)


def crm_login():
    jar = http.cookiejar.CookieJar()
    code, body, _ = http_request("POST", f"{CRM_URL}/login", data={"code": CRM_CODE}, cookies=jar)
    if code not in (200, 302):
        raise RuntimeError(f"CRM login fallo: HTTP {code}")
    return jar


def crm_create_lead(cookies, lead_data):
    code, body, _ = http_request(
        "POST", f"{CRM_URL}/api/leads",
        data=lead_data, headers={"Content-Type": "application/json"}, cookies=cookies
    )
    if code in (200, 201):
        return True, body
    return False, f"HTTP {code}: {body[:200]}"


_leads_cache = {"data": None}

def crm_check_lead_exists(cookies, phone):
    if not phone:
        return False
    if _leads_cache["data"] is None:
        params = urllib.parse.urlencode({"academia": ACADEMIA})
        code, body, _ = http_request("GET", f"{CRM_URL}/api/leads?{params}", cookies=cookies)
        if code != 200:
            return False
        try:
            _leads_cache["data"] = json.loads(body)
        except Exception:
            return False
    def norm(p):
        return (p or "").replace(" ", "").replace("-", "").lstrip("+").lstrip("3").lstrip("4")[-9:]
    target = norm(phone)
    if not target:
        return False
    for lead in _leads_cache["data"]:
        if norm(lead.get("telefono")) == target:
            return True
    return False


def meta_fetch_leads(form_id):
    url = f"https://graph.facebook.com/v25.0/{form_id}/leads"
    params = {
        "fields": "id,created_time,field_data,ad_id,campaign_id,form_id",
        "limit": "50",
        "access_token": PAGE_TOKEN,
    }
    url += "?" + urllib.parse.urlencode(params)
    code, body, _ = http_request("GET", url)
    if code != 200:
        print(f"[meta] Error fetching leads: {code} {body[:200]}", file=sys.stderr)
        return []
    data = json.loads(body)
    return data.get("data", [])


def meta_to_crm_format(meta_lead):
    fd = {f["name"]: (f["values"][0] if f["values"] else "") for f in meta_lead.get("field_data", [])}
    nombre = fd.get("full_name", "").strip()
    email = fd.get("email", "").strip()
    telefono = (fd.get("phone_number", "") or fd.get("whatsapp_number", "")).strip()
    telefono = telefono.replace(" ", "").replace("-", "")
    if telefono and not telefono.startswith("+") and len(telefono) == 9:
        telefono = "+34" + telefono
    elif telefono and telefono.startswith("34") and len(telefono) == 11:
        telefono = "+" + telefono
    esp_raw = (fd.get("specialty") or fd.get("cual_es_tu_especialidad") or "").strip().lower()
    especialidad = SPECIALTY_MAP.get(esp_raw, esp_raw or "")
    return {
        "nombre": nombre or "(Sin nombre)",
        "email": email,
        "telefono": telefono,
        "academia": ACADEMIA,
        "especialidad": especialidad,
        "estado": "nuevo",
        "notas": f"Lead Meta. campaign={meta_lead.get('campaign_id','')}, ad={meta_lead.get('ad_id','')}, lead_id={meta_lead.get('id','')}",
    }


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_processed": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def main():
    if not PAGE_TOKEN or not CRM_CODE:
        print("ERROR: faltan META_PAGE_TOKEN o CRM_CODE", file=sys.stderr)
        sys.exit(2)
    state = load_state()
    crm_cookies = crm_login()
    print(f"Logged into CRM ({CRM_URL})")
    total_new, total_dup, total_err = 0, 0, 0
    for form_id in FORM_IDS:
        leads = meta_fetch_leads(form_id)
        last_seen = state["last_processed"].get(form_id)
        new_leads = []
        for l in leads:
            if last_seen and l["id"] == last_seen:
                break
            new_leads.append(l)
        new_leads.reverse()
        print(f"  Form {form_id}: {len(new_leads)} nuevos a procesar")
        for meta_lead in new_leads:
            crm_data = meta_to_crm_format(meta_lead)
            if crm_check_lead_exists(crm_cookies, crm_data["telefono"]):
                print(f"    [dup] {crm_data['nombre']} ({crm_data['telefono']})")
                total_dup += 1
            else:
                ok, msg = crm_create_lead(crm_cookies, crm_data)
                if ok:
                    print(f"    [ok]  {crm_data['nombre']} ({crm_data['telefono']}) -- {crm_data['especialidad']}")
                    total_new += 1
                    push_notify(
                        title=f"Nuevo lead: {crm_data['nombre']}",
                        message=(
                            f"📞 {crm_data['telefono'] or '(sin teléfono)'}\n"
                            f"✉️ {crm_data['email'] or '(sin email)'}\n"
                            f"🎓 {crm_data['especialidad'] or '(sin especialidad)'}\n"
                            f"🏫 {ACADEMIA}"
                        ),
                        click_url=CRM_URL,
                        tags=["incoming_envelope"],
                        priority=4,
                    )
                else:
                    print(f"    [err] {msg}")
                    total_err += 1
                    push_notify(
                        title="Error creando lead de Meta",
                        message=msg[:200],
                        tags=["warning"],
                        priority=5,
                    )
            state["last_processed"][form_id] = meta_lead["id"]
            save_state(state)
    print(f"\nResumen: {total_new} nuevos, {total_dup} duplicados, {total_err} errores")


if __name__ == "__main__":
    main()
