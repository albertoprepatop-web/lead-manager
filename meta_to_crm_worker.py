#!/usr/bin/env python3
"""
Worker Meta Lead Ads -> CRM Multi-academia con detección de re-contacto.

Para cada lead nuevo de Meta:
  - Si NO existe en el CRM (por teléfono)  → lo crea y manda push.
  - Si existe y su estado es "nuevo"       → silencio (es el mismo lead aún sin tocar).
  - Si existe y ya fue contactado          → añade nota de "re-contacto" al lead
                                              y dispara push de re-contacto.
                                              Anti-spam: si la última nota de
                                              re-contacto fue añadida hace <24h,
                                              no añade nota ni push.

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
import datetime
import json
import os
import re
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

# Marcador y cooldown para notas de re-contacto (lead que repite el form Meta)
RECONTACT_PREFIX = "Volvió a rellenar form Meta"
RECONTACT_COOLDOWN_SECONDS = 24 * 3600

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
        "historia": "Geografía e Historia",
        "geografia_e_historia": "Geografía e Historia",
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


def _norm_phone(p):
    return (p or "").replace(" ", "").replace("-", "").lstrip("+").lstrip("3").lstrip("4")[-9:]


def crm_find_lead_by_phone(cookies, phone, academia):
    """Devuelve el dict del lead existente en la academia (o None)."""
    if not phone:
        return None
    if academia not in _leads_cache:
        params = urllib.parse.urlencode({"academia": academia})
        code, body, _ = http_request("GET", f"{CRM_URL}/api/leads?{params}", cookies=cookies)
        if code != 200:
            return None
        try:
            _leads_cache[academia] = json.loads(body)
        except Exception:
            return None
    target = _norm_phone(phone)
    if not target:
        return None
    for lead in _leads_cache[academia]:
        if _norm_phone(lead.get("telefono")) == target:
            return lead
    return None


def crm_update_lead(cookies, lead_id, updates):
    """PUT /api/leads/{id} con los campos a actualizar. Devuelve (ok, body)."""
    code, body, _ = http_request(
        "PUT", f"{CRM_URL}/api/leads/{lead_id}",
        data=updates, headers={"Content-Type": "application/json"}, cookies=cookies
    )
    if code in (200, 201, 204):
        return True, body
    return False, f"HTTP {code}: {body[:200]}"


def parse_last_recontact_dt(notes):
    """Devuelve datetime de la nota de re-contacto más reciente, o None."""
    if not notes:
        return None
    pattern = re.escape(RECONTACT_PREFIX) + r' (\d{4}-\d{2}-\d{2} \d{2}:\d{2})'
    matches = re.findall(pattern, notes)
    if not matches:
        return None
    try:
        return max(datetime.datetime.strptime(m, "%Y-%m-%d %H:%M") for m in matches)
    except Exception:
        return None


def extract_hora_preferida(field_data_dict):
    """Busca el valor de 'hora preferida' bajo varios nombres posibles."""
    candidates = [
        "hora_preferida", "hora_preferente", "horario", "horario_preferido",
        "best_time_to_call", "preferred_time", "mejor_hora",
        "cuando_te_puedo_llamar", "cuando_te_viene_bien",
    ]
    for key in candidates:
        v = field_data_dict.get(key)
        if v:
            return v.strip()
    return ""


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
    hora_pref = extract_hora_preferida(fd)
    return {
        "nombre": nombre or "(Sin nombre)",
        "email": email,
        "telefono": telefono,
        "academia": academia,
        "especialidad": especialidad,
        "hora_preferida": hora_pref,
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
            existing = crm_find_lead_by_phone(crm_cookies, crm_data["telefono"], academia)

            if existing is None:
                # Lead totalmente nuevo
                ok, msg = crm_create_lead(crm_cookies, crm_data)
                if ok:
                    print(f"    [ok]  {crm_data['nombre']} ({crm_data['telefono']}) -- {crm_data['especialidad']}")
                    total_new += 1
                    body = (
                        f"{crm_data['nombre']}\n"
                        f"Tel: {crm_data['telefono']}\n"
                        f"Esp: {crm_data['especialidad']}"
                    )
                    if crm_data.get("hora_preferida"):
                        body += f"\nHora pref: {crm_data['hora_preferida']}"
                    ntfy_send(academia, f"Nuevo lead {academia}", body)
                else:
                    print(f"    [err] {msg}")
                    total_err += 1
            elif existing.get("estado") == "nuevo":
                # Duplicado pero aún sin contactar — silencio total
                print(f"    [dup-pending] {crm_data['nombre']} ({crm_data['telefono']})")
                total_dup += 1
            else:
                # Re-contacto: lead que ya fue tocado y vuelve a rellenar el form
                now_dt = datetime.datetime.now()
                last_rc = parse_last_recontact_dt(existing.get("notas") or "")
                if last_rc and (now_dt - last_rc).total_seconds() < RECONTACT_COOLDOWN_SECONDS:
                    print(f"    [recontact-mute] {crm_data['nombre']} (<24h desde último re-contacto)")
                    total_dup += 1
                else:
                    fd = {f["name"]: (f["values"][0] if f["values"] else "") for f in meta_lead.get("field_data", [])}
                    hora_pref_raw = extract_hora_preferida(fd)
                    hora_pref = hora_pref_raw or "(no indicada)"
                    ad_id = meta_lead.get("ad_id", "")
                    esp = crm_data["especialidad"] or "(sin)"
                    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
                    new_note = (
                        f"{RECONTACT_PREFIX} {now_str} - Esp: {esp} "
                        f"- Hora pref: {hora_pref} - Ad: {ad_id}"
                    )
                    prev_notes = existing.get("notas") or ""
                    updated_notes = (prev_notes + "\n" + new_note) if prev_notes else new_note
                    updates = {"notas": updated_notes}
                    if hora_pref_raw:
                        # Si el lead ha cambiado su preferencia, la actualizamos
                        updates["hora_preferida"] = hora_pref_raw
                    ok, msg = crm_update_lead(crm_cookies, existing["id"], updates)
                    if ok:
                        print(f"    [recontact] {crm_data['nombre']} (estado={existing.get('estado')})")
                        existing["notas"] = updated_notes  # mantener cache coherente
                        if hora_pref_raw:
                            existing["hora_preferida"] = hora_pref_raw
                        body = (
                            f"Estado anterior: {existing.get('estado')}\n"
                            f"Esp: {esp}\n"
                            f"Tel: {crm_data['telefono']}\n"
                            f"Hora pref: {hora_pref}\n"
                            f"Fecha cita anterior: {existing.get('fecha_cita') or '(sin cita)'}"
                        )
                        ntfy_send(academia, f"Re-contacto {academia}: {crm_data['nombre']}", body)
                        total_dup += 1
                    else:
                        print(f"    [recontact-err] {msg}")
                        total_err += 1
            state["last_processed"][form_id] = meta_lead["id"]
            save_state(state)
    print(f"\nResumen: {total_new} nuevos, {total_dup} duplicados, {total_err} errores")


if __name__ == "__main__":
    main()
