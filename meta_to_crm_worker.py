#!/usr/bin/env python3
"""
Worker Meta Lead Ads -> CRM Multi-academia.
Variables de entorno:
  CRM_URL              — URL base del CRM
  CRM_CODE             — Código de acceso del CRM
  META_PAGE_TOKEN      — Page access token de Andalucia (nunca caduca)
  META_PAGE_TOKEN_SEC  — Page access token de Preparasecundaria (nunca caduca)
  FORM_ACADEMIA_MAP    — JSON. Ej:
                         {"1724817935180111":"PREPARAANDALUCIA",
                          "1310750974523839":"PREPARASECUNDARIA"}
  NTFY_BY_ACADEMIA     — JSON. Ej:
                         {"PREPARAANDALUCIA":"topic-alberto",
                          "PREPARASECUNDARIA":"topic-diego"}
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import http.cookiejar
from pathlib import Path

CRM_URL = os.environ.get("CRM_URL", "https://empathetic-strength-production-53db.up.railway.app").rstrip("/")
CRM_CODE = os.environ.get("CRM_CODE", "")
PAGE_TOKEN_AND = os.environ.get("META_PAGE_TOKEN", "")
PAGE_TOKEN_SEC = os.environ.get("META_PAGE_TOKEN_SEC", "")
FORM_ACADEMIA_MAP = json.loads(os.environ.get("FORM_ACADEMIA_MAP", "{}"))
NTFY_BY_ACADEMIA = json.loads(os.environ.get("NTFY_BY_ACADEMIA", "{}"))
STATE_FILE = Path(os.environ.get("STATE_FILE", "/tmp/meta_crm_state.json"))

TOKEN_BY_ACADEMIA = {
    "PREPARAANDALUCIA": PAGE_TOKEN_AND,
    "PREPARASECUNDARIA": PAGE_TOKEN_SEC,
}

SPECIALTY_MAPS = {
    "PREPARAANDALUCIA": {
        "infantil": "Infantil",
        "primaria": "Primaria",
        "educacion_fisica": "EF",
        "audicion_y_lenguaje": "AL",
        "pedagogia_terapeutica": "PT",
    },
    "PREPARASECUNDARIA": {
        "lengua_castellana": "Lengua Castellana",
        "historia": "Historia",
        "musica": "Música",
        "tecnologia": "Tecnología",
        "ingles": "Inglés",
        "educacion_fisica": "EF",
    },
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
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies)) if cookies is not None else urllib.request.build_opener()
    try:
        resp = opener.open(req, timeout=30)
        return resp.status, resp.read().decode("utf-8", errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), dict(e.headers)


def crm_login():
    jar = http.cookiejar.CookieJar()
    code, body, _ = http_request("POST", f"{CRM_URL}/login", data={"code": CRM_CODE}, cookies=jar)
    if code not in (200, 302):
        raise RuntimeError(f"CRM login fallo: HTTP {code}")
    return jar


def crm_create_lead(cookies, lead_data):
    code, body, _ = http_request("POST", f"{CRM_URL}/api/leads", data=lead_data,
                                  headers={"Content-Type": "application/json"}, cookies=cookies)
    if code in (200, 201):
        return True, body
    return False, f"HTTP {code}: {body[:200]}"


_leads_cache = {}

def crm_check_lead_exists(cookies, phone, academia):
    if not phone:
        return False
    if academia not in _leads_cache:
        params = urllib.parse.urlencode({"academia": academia})
        code, body, _ = http_request("GET", f"{CRM_URL}/api/leads?{params}", cookies=cookies)
        if code != 200:
            return False
        try:
            _leads_cache[academia] = json.loads(body)
        except Exception:
            return False
    def norm(p):
        return (p or "").replace(" ", "").replace("-", "").lstrip("+").lstrip("3").lstrip("4")[-9:]
    target = norm(phone)
    if not target:
        return False
    for lead in _leads_cache[academia]:
        if norm(lead.get("telefono")) == target:
            return True
    return False


def meta_fetch_leads(form_id, token):
    url = f"https://graph.facebook.com/v25.0/{form_id}/leads"
    params = {"fields": "id,created_time,field_data,ad_id,campaign_id,form_id", "limit": "50", "access_token": token}
    url += "?" + urllib.parse.urlencode(params)
    code, body, _ = http_request("GET", url)
    if code != 200:
        print(f"[meta] Error fetching {form_id}: {code} {body[:200]}", file=sys.stderr)
        return []
    return json.loads(body).get("data", [])


def meta_to_crm_format(meta_lead, academia):
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
    especialidad = SPECIALTY_MAPS.get(academia, {}).get(esp_raw, esp_raw or "")
    return {
        "nombre": nombre or "(Sin nombre)",
        "email": email,
        "telefono": telefono,
        "academia": academia,
        "especialidad": especialidad,
        "estado": "nuevo",
        "notas": f"Lead Meta. campaign={meta_lead.get('campaign_id','')}, ad={meta_lead.get('ad_id','')}, lead_id={meta_lead.get('id','')}",
    }


def ntfy_send(academia, title, message):
    topic = NTFY_BY_ACADEMIA.get(academia)
    if not topic:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            method="POST",
            headers={"Title": title, "Priority": "high", "Tags": "tada,bell"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[ntfy] Error: {e}", file=sys.stderr)


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
    if not CRM_CODE or not FORM_ACADEMIA_MAP:
        print("ERROR: faltan CRM_CODE o FORM_ACADEMIA_MAP", file=sys.stderr)
        sys.exit(2)
    state = load_state()
    crm_cookies = crm_login()
    print(f"OK CRM ({CRM_URL})")
    total_new = total_dup = total_err = 0
    for form_id, academia in FORM_ACADEMIA_MAP.items():
        token = TOKEN_BY_ACADEMIA.get(academia)
        if not token:
            print(f"  [skip] Form {form_id} sin token para {academia}", file=sys.stderr)
            continue
        leads = meta_fetch_leads(form_id, token)
        last_seen = state["last_processed"].get(form_id)
        new_leads = []
        for l in leads:
            if last_seen and l["id"] == last_seen:
                break
            new_leads.append(l)
        new_leads.reverse()
        print(f"  Form {form_id} [{academia}]: {len(new_leads)} nuevos")
        for meta_lead in new_leads:
            crm_data = meta_to_crm_format(meta_lead, academia)
            if crm_check_lead_exists(crm_cookies, crm_data["telefono"], academia):
                print(f"    [dup] {crm_data['nombre']} ({crm_data['telefono']})")
                total_dup += 1
            else:
                ok, msg = crm_create_lead(crm_cookies, crm_data)
                if ok:
                    print(f"    [ok]  {crm_data['nombre']} ({crm_data['telefono']}) -- {crm_data['especialidad']}")
                    total_new += 1
                    ntfy_send(academia, f"Nuevo lead {academia}",
                              f"{crm_data['nombre']}\nTel: {crm_data['telefono']}\nEsp: {crm_data['especialidad']}")
                else:
                    print(f"    [err] {msg}")
                    total_err += 1
            state["last_processed"][form_id] = meta_lead["id"]
            save_state(state)
    print(f"\nResumen: {total_new} nuevos, {total_dup} duplicados, {total_err} errores")


if __name__ == "__main__":
    main()
