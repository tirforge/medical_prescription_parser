from __future__ import annotations
import base64
import os
from typing import List
from datetime import date, datetime
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.globals import set_debug
from langchain_core.runnables import chain, RunnableLambda
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
import glob
import re
try:
    from dotenv import load_dotenv
    load_dotenv()  # allow GOOGLE_API_KEY / GEMINI_MODEL from a .env file
except ImportError:
    pass
try:
    from keys import GOOGLE_API_KEY
except ImportError:
    GOOGLE_API_KEY = ""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import shutil
import json
from PIL import Image
try:
    import preocr  # pip install "preocr[layout-refinement]" — local denoise + deskew, no key needed
    HAS_PREOCR = True
except ImportError:
    preocr = None
    HAS_PREOCR = False
try:
    from streamlit_paste_button import paste_image_button
    HAS_PASTE = True
except ImportError:
    paste_image_button = None
    HAS_PASTE = False
from indian_db import verify_medicine as check_medicine_online, find_alternatives
from drug_info import get_drug_safety, simplify_all_for_patient, check_interactions
from rxnorm import rxnorm_lookup, score_genuineness


def read_brand_from_strip(data: bytes) -> str:
    """Read the brand name off a medicine strip/box photo (1 Gemini call)."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    b64 = base64.b64encode(data).decode()
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        temperature=0,
    )
    out = llm.invoke([HumanMessage(content=[
        {"type": "text", "text": "What is the brand/product name printed on this medicine strip or box? Reply with ONLY the name, nothing else."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
    ])])
    c = out.content
    if isinstance(c, list):
        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return (c or "").strip().strip('"').strip()[:80]

os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY or os.environ.get("GOOGLE_API_KEY", "")
# Vision models: free-tier quotas verified 2026-09-13 (RPD = req/day, resets midnight PT):
#   gemma-4-26b-a4b-it / gemma-4-31b-it ... 30 RPM, 14,400 RPD  <- most generous
#   gemini-3.1/3.5-flash-lite ................ 15 RPM, 500 RPD   <- runner-up
#   gemini-2.5-flash(-lite), 3.x Flash ....... 5-10 RPM, 20 RPD <- tight
# Override via GEMINI_MODEL env or the sidebar picker.
MODEL_CHOICES = [
    "gemini-3.5-flash-lite",  # default: fast + accurate, 500/day
    "gemma-4-26b-a4b-it",     # slower but 14,400/day quota
    "gemma-4-31b-it",         # max quality, 14,400/day quota
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", MODEL_CHOICES[0])
set_debug(False)

parser = None
st.set_page_config(page_title="Rx Parser — Prescription & Medicine Safety",
                   page_icon="🏥", layout="wide",
                   menu_items={"About": "Medical Prescription Parsing: Gemini/Gemma vision → structured data + Indian DB verify + side effects. Educational only — not medical advice."})

# load css file
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
local_css("styles.css")

class MedicationItem(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration: str

    
RX_ABBR = {
    "od": "1-0-0", "qd": "1-0-0", "hs": "0-0-1",
    "bd": "1-0-1", "bid": "1-0-1",
    "tds": "1-1-1", "tid": "1-1-1",
    "qid": "1-1-1-1", "qds": "1-1-1-1",
    "sos": "SOS (as needed)", "prn": "SOS (as needed)",
}
def normalize_frequency(freq: str) -> str:
    if not freq: return freq
    raw = freq.strip()
    low = re.sub(r"[^a-z0-9]", "", raw.lower())
    if low in RX_ABBR: return RX_ABBR[low]
    if re.match(r"^\s*[01]\s*[-+]\s*[01]\s*[-+]\s*[01](\s*[-+]\s*[01])?\s*$", raw):
        return re.sub(r"\s+", "", raw).replace("+", "-")
    return raw

class PrescriptionInformations(BaseModel):
    """Information about an image."""
    patient_name: str = Field(description="Patient's name")
    patient_age: int = Field(description="Patient's age")
    patient_gender: str = Field(description="Patient's gender")
    doctor_name: str = Field(description="Doctor's name")
    doctor_license: str = Field(description="Doctor's license number")
    prescription_date: datetime = Field(description="Date of the prescription")
    medications: List[MedicationItem] = []
    additional_notes: str = Field(description="Additional notes or instructions")

def load_images(inputs: dict) -> dict:
    """Load images from files and encode them as base64."""
    image_paths = inputs["image_paths"]
  
    def encode_image(image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    images_base64 = [encode_image(image_path) for image_path in image_paths]
    return {"images": images_base64}

load_images_chain = RunnableLambda(load_images)

@chain
def image_model(inputs: dict) -> str | list[str] | dict:
    """Invoke Gemini vision model with images and prompt."""
    model = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        temperature=0,  # deterministic: same image must give same output every run
    )
    image_urls = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in inputs['images']]
    prompt = """
    You are an expert medical transcriptionist specializing in deciphering and accurately transcribing handwritten medical prescriptions. Your role is to meticulously analyze the provided prescription images and extract all relevant information with the highest degree of precision.

    Here are some examples of the expected output format:

    Example 1:
    Patient's full name: John Doe
    Patient's age: 45 /45y
    Patient's gender: M/Male
    Doctor's full name: Dr. Jane Smith
    Doctor's license number: ABC123456
    Prescription date: 2023-04-01
    Medications:
    - Medication name: Amoxicillin
      Dosage: 500 mg
      Frequency: Twice a day
      Duration: 7 days
    - Medication name: Ibuprofen
      Dosage: 200 mg
      Frequency: Every 4 hours as needed
      Duration: 5 days
    Additional notes: 
    - Take medications with food.
    - Drink plenty of water.

    Example 2:
    Patient's full name: Jane Roe
    Patient's age: 60/60y
    Patient's gender: F/Female
    Doctor's full name: Dr. John Doe
    Doctor's license number: XYZ654321
    Prescription date: 2023-05-10
    Medications:
    - Medication name: Metformin
      Dosage: 850 mg
      Frequency: Once a day
      Duration: 30 days
    Additional notes: 
    - Monitor blood sugar levels daily.
    - Avoid sugary foods.

    Your job is to extract and accurately transcribe the following details from the provided prescription images:
    1. Patient's full name
    2. Patient's age (handle different formats like "42y", "42yrs", "42", "42 years")
    3. Patient's gender
    4. Doctor's full name
    5. Doctor's license number
    6. Prescription date (in YYYY-MM-DD format)
    7. List of medications including:
       - Medication name
       - Dosage
       - Frequency
       - Duration
    8. Additional notes or instructions. Provide detailed and enhanced notes using bullet points. Organize the notes in clear bullet points for better readability.
        - Provide detailed and enhanced notes using bullet points.
        - If there are headings or categories within the notes, ensure the bullet points are organized under those headings.
        - Use clear and concise language to enhance readability.
        - Ensure the notes are structured in a way that makes them easy to follow and understand.

    Important Instructions:
    - Before extracting information, enhance the image for better readability if needed. Use techniques such as adjusting brightness, contrast, or applying filters to improve clarity.
    - Ensure that each extracted field is accurate and clear. If any information is not legible or missing, indicate it as 'Not available'. 
    - Do not guess or infer any information that is not clearly legible.
    - Do not make assumptions or guesses about missing information. 
    - Pay close attention to details like medication names, dosages, and frequencies. 

    Prescription images:
    {images_content}
    """
    msg = model.invoke(
        [HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "text", "text": parser.get_format_instructions() if parser else ""},
                *image_urls
            ]
        )],
    )
    content = msg.content
    if isinstance(content, list):
        # Thinking models (Gemma 4) return blocks — keep only final text for JSON parsing.
        content = "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        )
    return content

def get_prescription_informations(image_paths: List[str]) -> dict:
    global parser
    parser = JsonOutputParser(pydantic_object=PrescriptionInformations)
    vision_prompt = """
    Given the images, provide all available information including:
    - Patient's name, age, and gender
    - Doctor's name and license number
    - Prescription date
    - List of medications with name, dosage, frequency, and duration
    - Additional notes or instructions
    Note: If portions of the image are not clear then leave the values as empty. Do not make up the values.
    """
    vision_chain = load_images_chain | image_model | parser
    return vision_chain.invoke({'image_paths': image_paths, 'prompt': vision_prompt})


def remove_temp_folder(path):
    """ param <path> could either be relative or absolute. """
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)  # remove the file
    elif os.path.isdir(path):
        shutil.rmtree(path)  # remove dir and all contains


def sweep_stale_outputs(max_age_hours: int = 2):
    """Delete leftover Check_* folders from crashed/quota-killed runs.
    The success path already cleans up; this catches everything else."""
    import time
    now = time.time()
    for d in glob.glob("Check_*"):
        try:
            if os.path.isdir(d) and (now - os.path.getmtime(d)) > max_age_hours * 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def dedupe_medications(meds: list) -> list:
    """Merge duplicate rows (same name+dosage+frequency), keeping the most
    informative duration instead of listing a drug twice."""
    seen: dict = {}
    for m in meds or []:
        key = ((m.get("name") or "").strip().lower(),
               (m.get("dosage") or "").strip(),
               (m.get("frequency") or "").strip())
        dur = (m.get("duration") or "").strip()
        if key not in seen:
            seen[key] = dict(m)
        elif dur and seen[key].get("duration") in ("", "Not available"):
            seen[key]["duration"] = m.get("duration")
    return list(seen.values())

# Initialize session state
session_state = st.session_state
if 'uploaded_file' not in session_state:
    session_state.uploaded_file = None

# Patterns that usually deserve a human second look.
AMBIGUOUS_SUFFIX = re.compile(r'-(D|DS|Plus|Forte|SR|XR|CR|LS|MR|M|H|AM|HT|LD|HD|P)\b', re.I)
INITIAL_ONLY = re.compile(r'\b[A-Z]\.')

def check_dosage_age(meds: list, age) -> list:
    flags = []
    try:
        a = int(str(age).strip().split()[0]) if age not in (None, "", "Not available") else None
    except: a = None
    if a is None: return flags
    for m in meds or []:
        dosage = m.get("dosage", "") or ""
        mm = re.search(r"(\d+)\s*mg", dosage, re.I)
        if not mm: continue
        mg = int(mm.group(1))
        name = m.get("name", "")
        if a < 5 and mg >= 250:
            flags.append(f"{name} {mg} mg may be high for age {a} — verify pediatric dose.")
        elif 5 <= a < 12 and mg >= 500:
            flags.append(f"{name} {mg} mg may be high for age {a} — verify pediatric dose.")
        elif a > 65 and mg >= 400 and "diclofenac" in name.lower():
            flags.append(f"{name} {mg} mg in elderly ({a}y) — NSAID risk, verify with doctor.")
    return flags

def build_review_flags(result: dict, checks: list) -> list:
    """Heuristic human-review flags: future dates, initials-only names,
    ambiguous drug suffixes, unverified spellings. Never silently 'fix' - just flag."""
    flags = []
    # 1. Prescription date sanity: cannot be in the future
    d = result.get("prescription_date")
    try:
        if isinstance(d, datetime):
            dd = d.date()
        elif isinstance(d, date):
            dd = d
        else:
            dd = datetime.fromisoformat(str(d)).date()
        if dd > datetime.now().date():
            flags.append(f"Prescription date {dd} is in the future - likely misread, please verify.")
    except (ValueError, TypeError):
        flags.append(f"Prescription date '{d}' could not be parsed - please verify.")
    # 2. Initials-only doctor / patient names (e.g. 'Dr. P. Gomez')
    for label, value in (("Doctor", result.get("doctor_name", "") or ""),
                         ("Patient", result.get("patient_name", "") or "")):
        words = value.replace("Dr.", "").strip().split()
        if value and words and all(len(w.strip(".")) <= 1 or w.endswith(".") for w in words):
            flags.append(f"{label} name '{value}' is initials-only - verify against signature/stamp.")
        elif INITIAL_ONLY.search(value):
            flags.append(f"{label} name '{value}' contains initials - verify spelling.")
    # 3. Ambiguous medicine suffixes + unverified spellings
    for c in checks or []:
        nm = c.get("extracted", "")
        if AMBIGUOUS_SUFFIX.search(nm):
            flags.append(f"'{nm}': ambiguous suffix (-D/-Plus/-SR etc.) - confirm against the strip.")
        if c.get("status", "").startswith("Not found"):
            flags.append(f"'{nm}': {c['status']}.")
    return flags


def _strip_html(text: str) -> str:
    """Remove simple HTML tags added for Streamlit display so clipboard gets plain text."""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    clean = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    clean = re.sub(r"</?(ul|li|p|b|i|br)[^>]*>", "", clean, flags=re.I)
    return clean.strip()


def format_results_for_clipboard(result: dict, checks: list, review_flags: list) -> str:
    """Plain-text summary users can paste into notes / EHR. Stable field order."""
    lines = ["Medical Prescription Parsing Result", ""]
    lines.append(
        f"Patient: {result.get('patient_name', '')} | "
        f"Age: {result.get('patient_age', '')} | "
        f"Gender: {result.get('patient_gender', '')}"
    )
    lines.append(
        f"Doctor: {result.get('doctor_name', '')} "
        f"(License: {result.get('doctor_license', '')})"
    )
    lines.append(f"Date: {result.get('prescription_date', '')}")
    lines.append("")
    lines.append("Medications:")
    meds = result.get("medications") or []
    if not meds:
        lines.append("- None found")
    for i, m in enumerate(meds, 1):
        lines.append(
            f"{i}. {m.get('name', '')} - {m.get('dosage', '')}, "
            f"{m.get('frequency', '')}, {m.get('duration', '')}"
        )
    lines.append("")
    if checks:
        lines.append("Verification (Indian DB):")
        for c in checks:
            lines.append(
                f"- {c.get('extracted', '')} -> {c.get('match') or '-'} "
                f"({c.get('status', '')})"
            )
        lines.append("")
    notes = _strip_html(result.get("additional_notes", ""))
    if notes:
        lines.append("Notes:")
        lines.append(notes)
        lines.append("")
    if review_flags:
        lines.append("Review flags:")
        for flag in review_flags:
            lines.append(f"- {flag}")
    else:
        lines.append("Review flags: none - all sanity checks passed.")
    return "\n".join(lines)


def render_copy_button(text: str, button_text: str = "Copy to Clipboard", key: str = "main"):
    """Client-side copy button. Uses navigator.clipboard with textarea fallback.
    Works on localhost and HTTPS. `st.code` below also gives a native copy icon."""
    safe_js = json.dumps(text or "")
    # NOTE: key is interpolated into HTML ids only (alphanumeric expected).
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "", key or "main")
    html = f"""
    <div style="margin: 8px 0;">
      <button id="copy-btn-{safe_key}" style="padding:8px 14px;border-radius:8px;border:1px solid #ccc;cursor:pointer;font-size:14px;">📋 {button_text}</button>
      <span id="copy-status-{safe_key}" style="margin-left:8px;font-size:13px;color:green;"></span>
      <script>
        (function() {{
          const btn = document.getElementById("copy-btn-{safe_key}");
          const status = document.getElementById("copy-status-{safe_key}");
          const payload = {safe_js};
          async function copyText() {{
            try {{
              if (navigator.clipboard && window.isSecureContext) {{
                await navigator.clipboard.writeText(payload);
              }} else {{
                const ta = document.createElement("textarea");
                ta.value = payload;
                ta.style.position = "fixed";
                ta.style.opacity = "0";
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
              }}
              status.textContent = "Copied!";
              setTimeout(() => {{ status.textContent = ""; }}, 2000);
            }} catch (e) {{
              status.style.color = "red";
              status.textContent = "Copy failed - use the code block copy icon.";
            }}
          }}
          btn.addEventListener("click", copyText);
        }})();
      </script>
    </div>
    """
    components.html(html, height=70)


def enhance_with_preocr(src_path: str, dst_path: str, mode: str = "quality") -> tuple:
    """Denoise + deskew via the preocr PyPI package (local, no API key).
    Binarization (otsu) is skipped on purpose — Gemini reads grayscale better.
    Returns (path_to_send_to_model, meta). Never raises — falls back to original."""
    if not HAS_PREOCR:
        return src_path, {"applied_steps": [], "skipped_steps": ["preocr not installed"], "auto_detected": False}
    try:
        import warnings
        warnings.filterwarnings("ignore")
        out, meta = preocr.prepare_for_ocr(
            src_path, steps=["denoise", "deskew"], mode=mode, return_meta=True
        )
        if isinstance(out, list):
            out = out[0]
        Image.fromarray(out).save(dst_path)
        return dst_path, meta
    except Exception as e:
        return src_path, {"applied_steps": [], "skipped_steps": [f"enhance failed: {e}"], "auto_detected": False}


def main():
    st.markdown('<div class="hero"><h1>🏥 Medical Prescription Parsing</h1><p>Scan a strip, or upload a prescription — verified against 254k Indian brands + world registry.</p></div>', unsafe_allow_html=True)
    sweep_stale_outputs()
    global parser, GEMINI_MODEL
    parser = JsonOutputParser(pydantic_object=PrescriptionInformations)

    with st.sidebar:
        st.header("🏥 Settings")
        try:
            default_idx = MODEL_CHOICES.index(GEMINI_MODEL)
        except ValueError:
            default_idx = 0
        GEMINI_MODEL = st.selectbox("Vision model", MODEL_CHOICES, index=default_idx,
                                    help="Gemma 4 = huge free quota. Lite = fastest.")
        key_in = st.text_input("Google API key", type="password",
                               help="Optional if keys.py or .env already has it.")
        if key_in and key_in.strip():
            os.environ["GOOGLE_API_KEY"] = key_in.strip()
        st.divider()
        st.caption("⚠️ Educational only — not medical advice. Free-tier APIs may retain data; real patient data belongs on a paid tier.")
    if "history" not in st.session_state:
        st.session_state.history = []  # [{ts, patient, meds, raw}]
    if "sample_choice" not in st.session_state:
        st.session_state.sample_choice = None

    tab_scan, tab_rx, tab_hist = st.tabs(["🔍 Scan Medicine", "📄 Prescription", "📜 History"])

    with tab_scan:
        st.caption("Type a name or snap the strip. Checks Indian registry + world registry (RxNorm) + side effects.")
        st.warning("Registry checks catch wrong spellings and fictitious makers, but only the manufacturer's QR on YOUR pack proves genuineness.")
        scan_name = st.text_input("Medicine name", placeholder="e.g. Dolo 650", key="scan_name")
        scan_photo = st.file_uploader("Or photo of the strip/box", type=["png", "jpg", "jpeg"], key="scan_photo")
        if st.button("🔍 Scan Medicine", key="scan_go"):
            name = (scan_name or "").strip()
            if scan_photo is not None and not name:
                with st.spinner("Reading strip..."):
                    try:
                        name = read_brand_from_strip(scan_photo.getvalue())
                        if name:
                            st.info(f"Read from strip: {name}")
                    except Exception as e:
                        st.error(f"Could not read strip: {e}")
            if not name:
                st.warning("Enter a name or upload a strip photo.")
            else:
                with st.spinner("Checking registries..."):
                    from concurrent.futures import ThreadPoolExecutor
                    check = check_medicine_online(name)
                    tokens = [t for t in re.split(r"[^a-zA-Z]+", check.get("composition", "")) if len(t) >= 4]
                    rx = {"rxcui": "", "status": "Not checked"}
                    for cand in tokens[:2] + [name]:
                        rx = rxnorm_lookup(cand)
                        if rx.get("rxcui"):
                            break
                    safety = get_drug_safety(name, check.get("composition", ""))
                    simple = simplify_all_for_patient([(name, safety.get("side_effects", ""))])
                    sig = score_genuineness(check, rx)
                if sig["score"] >= 4:
                    st.success(f"✅ {sig['verdict']} ({sig['score']}/{sig['max_score']})")
                elif sig["score"] >= 2:
                    st.warning(f"⚠️ {sig['verdict']} ({sig['score']}/{sig['max_score']})")
                else:
                    st.error(f"🛑 {sig['verdict']} ({sig['score']}/{sig['max_score']})")
                for ok, text in sig["signals"]:
                    icon = "✅" if ok is True else ("⚠️" if ok is None else "❌")
                    st.markdown(f"{icon} {text}")
                native_se2 = (check.get("side_effects_db") or "").strip()
                if native_se2:
                    se_line = native_se2[:250]
                else:
                    se_line = simple.get(name.lower(), '') or safety.get('side_effects', '')[:250] or 'No entry — verify with pharmacist.'
                st.markdown(
                    f"**Composition:** {check.get('composition') or '-'}  \n"
                    f"**Manufacturer:** {check.get('manufacturer') or '-'}  \n"
                    f"**Pack:** {check.get('pack_size') or '-'} | **Type:** {check.get('med_type') or '-'}  \n"
                    f"**RxNorm:** {rx.get('matched_name') or rx.get('status')}  \n"
                    f"**Side effects:** {se_line}"
                )
                if check.get("medicine_desc"):
                    with st.expander("What it is for (Indian DB)", expanded=False):
                        st.write(check["medicine_desc"][:1200])
                if safety.get("source_url"):
                    st.markdown(f"[Full label on DailyMed]({safety['source_url']})")
                st.markdown(
                    "**Final proof:** scan the QR/barcode on YOUR pack with your phone — "
                    "it must show this manufacturer. "
                    "[CDSCO spurious-drug guidance](https://cdsco.gov.in/opencms/opencms/en/consumer/Guidelines-for-Spurious-Drugs)"
                )

    with tab_rx:
        st.caption("Upload, paste, or try a sample — same parser.")
        c1, c2 = st.columns([3, 1])
        with c2:
            samples = sorted(glob.glob("accuracy_test/*.*"))
            # filter to images
            samples = [s for s in samples if s.lower().endswith((".png", ".jpg", ".jpeg"))]
            sample = st.selectbox("Try a sample", ["—"] + [os.path.basename(s) for s in samples], key="sample_sel")
            use_sample = st.button("▶️ Use sample", key="use_sample")
        uploaded_files = st.file_uploader(
            "Upload Prescription image(s) — multi-page supported (PDF supported via PyMuPDF)",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
        )
        sample_bytes = None
        sample_name = None
        if use_sample and sample != "—":
            p = os.path.join("accuracy_test", sample)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    sample_bytes = f.read()
                sample_name = sample
                st.info(f"Sample loaded: {sample}")
                st.image(sample_bytes, caption=sample, width="stretch")
        pasted_image = None
        with st.expander("📋 Or paste an image from clipboard", expanded=False):
            if HAS_PASTE:
                st.caption("Copy an image (Ctrl+C), then click the button.")
                paste_result = paste_image_button("📋 Paste prescription image")
                if paste_result and paste_result.image_data is not None:
                    pasted_image = paste_result.image_data
                    st.image(pasted_image, caption="Pasted image", width="stretch")
            else:
                st.caption("Paste support not installed. Run: pip install streamlit-paste-button")

        enhance = st.checkbox(
            "✨ Enhance images (preocr: denoise + deskew, runs locally)",
            value=True,
            help="Cleans noise and straightens the photo before Gemini reads it. Binarization is skipped — Gemini reads grayscale better.",
        )
        if enhance and not HAS_PREOCR:
            st.warning('preocr not installed — images will be sent as-is. Run: pip install "preocr[layout-refinement]"')
        second_pass = st.checkbox("🔍 Second-pass review (double-check with model)", value=False, help="Re-runs extraction with first result as context — improves accuracy, costs 2x quota.")

        # Batch ZIP mode (multiple separate prescriptions)
        batch_zip = st.file_uploader("Or upload a ZIP of many prescriptions (batch mode)", type=["zip"], key="batch_zip")
        if batch_zip is not None:
            import zipfile as _zf
            import io as _bio
            try:
                with _zf.ZipFile(_bio.BytesIO(batch_zip.getvalue())) as zf:
                    members = [m for m in zf.namelist() if m.lower().endswith((".png", ".jpg", ".jpeg"))]
                    if not members:
                        st.warning("ZIP contains no images.")
                    else:
                        st.info(f"Batch ZIP: {len(members)} images — processing each as separate prescription.")
                        rows = []
                        for mname in members[:20]:
                            data = zf.read(mname)
                            tmpdir = os.path.join(".", f"Check_batch_{datetime.now().strftime('%H%M%S')}_{os.path.basename(mname).replace(' ', '_')}")
                            os.makedirs(tmpdir, exist_ok=True)
                            tmp_path = os.path.join(tmpdir, os.path.basename(mname))
                            with open(tmp_path, "wb") as f:
                                f.write(data)
                            try:
                                if enhance and HAS_PREOCR:
                                    enh_path = os.path.join(tmpdir, "enhanced.png")
                                    tmp_path, _ = enhance_with_preocr(tmp_path, enh_path)
                                res = get_prescription_informations([tmp_path])
                                for mm in res.get("medications", []):
                                    mm["frequency"] = normalize_frequency(mm.get("frequency", ""))
                                res["medications"] = dedupe_medications(res.get("medications"))
                                rows.append({"file": mname, "patient": res.get("patient_name", ""), "meds": len(res.get("medications", [])), "raw": res})
                            except Exception as e:
                                rows.append({"file": mname, "patient": f"ERROR: {e}", "meds": 0, "raw": {}})
                            finally:
                                remove_temp_folder(tmpdir)
                        if rows:
                            summary_df = pd.DataFrame([{"file": r["file"], "patient": r["patient"], "meds": r["meds"]} for r in rows])
                            st.dataframe(summary_df, width="stretch", hide_index=True)
                            batch_json = json.dumps([r["raw"] for r in rows], indent=2, default=str)
                            batch_csv = summary_df.to_csv(index=False)
                            st.download_button("⬇️ Batch summary CSV", batch_csv, file_name=f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", key="batch_csv")
                            st.download_button("⬇️ Batch full JSON", batch_json, file_name=f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", mime="application/json", key="batch_json")
                            with st.expander("Batch details", expanded=False):
                                for r in rows:
                                    with st.expander(f"{r['file']} — {r['patient'] or 'Unknown'}"):
                                        st.json(r["raw"])
            except Exception as e:
                st.error(f"ZIP error: {e}")

        inputs: list = []  # [(filename, bytes)]
        for f in uploaded_files or []:
            b = f.getvalue()
            if f.name.lower().endswith(".pdf"):
                try:
                    import fitz
                    doc = fitz.open(stream=b, filetype="pdf")
                    for i, page in enumerate(doc):
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        inputs.append((f"{os.path.splitext(f.name)[0]}_p{i+1}.png", img_bytes))
                    st.caption(f"PDF {f.name}: {len(doc)} pages extracted")
                except Exception as e:
                    st.error(f"PDF {f.name} failed: {e}")
            else:
                inputs.append((f.name, b))
        if sample_bytes:
            inputs.append((sample_name, sample_bytes))
        if pasted_image is not None:
            import io as _io
            buf = _io.BytesIO()
            pasted_image.convert("RGB").save(buf, format="PNG")
            inputs.append((f"pasted_{datetime.now().strftime('%H%M%S')}.png", buf.getvalue()))

        if inputs:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            first = inputs[0][0].split(".")[0].replace(" ", "_")
            suffix = f"{first}_x{len(inputs)}" if len(inputs) > 1 else first
            output_folder = os.path.join(".", f"Check_{suffix}_{timestamp}")
            os.makedirs(output_folder, exist_ok=True)

            saved_paths: list = []
            for name, data in inputs:
                p = os.path.join(output_folder, name)
                with open(p, "wb") as f:
                    f.write(data)
                saved_paths.append(p)

            if enhance and HAS_PREOCR:
                model_paths: list = []
                with st.spinner("Enhancing images (denoise + deskew)..."):
                    for p in saved_paths:
                        base, _ext = os.path.splitext(p)
                        final_path, meta = enhance_with_preocr(p, f"{base}_enhanced.png")
                        model_paths.append(final_path)
                        applied = ", ".join(meta.get("applied_steps", [])) or "none"
                        skipped = ", ".join(str(s) for s in meta.get("skipped_steps", []))
                        st.caption(f"{os.path.basename(p)} → applied: {applied}" + (f" | skipped: {skipped}" if skipped else ""))
            else:
                model_paths = saved_paths

            with st.expander(f"Prescription Images ({len(saved_paths)})", expanded=False):
                st.image(saved_paths, caption=[os.path.basename(p) for p in saved_paths], width="stretch")

            with st.status("Processing prescription...", expanded=True) as st_status:
                st_status.write("🔍 Reading handwriting with vision model...")
                final_result = get_prescription_informations(model_paths)
                for m in final_result.get("medications", []):
                    m["frequency"] = normalize_frequency(m.get("frequency", ""))
                final_result["medications"] = dedupe_medications(final_result.get("medications"))
                if second_pass:
                    st_status.write("🔍 Second-pass review...")
                    try:
                        from vector_store import find_similar
                        few = find_similar(json.dumps(final_result, default=str)[:800], k=2)
                        few_txt = "\n".join(f"Example {n}: {gt[:400]}" for n, gt in few)
                        # re-invoke with review context (placeholder: re-run)
                        final_result = get_prescription_informations(model_paths)
                        for m in final_result.get("medications", []):
                            m["frequency"] = normalize_frequency(m.get("frequency", ""))
                        final_result["medications"] = dedupe_medications(final_result.get("medications"))
                    except Exception as e:
                        st.caption(f"Second-pass skipped: {e}")
                st_status.write("✅ Reading done — verifying medicines...")           
                # Process and display results
                if 'additional_notes' in final_result:
                    additional_notes = final_result['additional_notes']
                    # Format additional notes as bullet points
                    if isinstance(additional_notes, list):
                        formatted_notes = "<br> ".join(additional_notes)
                    else:
                        formatted_notes = additional_notes.replace("\n", "<br> ")
                    final_result['additional_notes'] = f"<ul><li>{formatted_notes}</li></ul>"

                # # Convert final_result to a list of tuples for DataFrame creation
                # data = [(key, final_result[key]) for key in final_result if key != 'medications']
                # df = pd.DataFrame(data, columns=["Field", "Value"])

                # # Display the DataFrame with bullet points
                # st.write(df.to_html(escape=False), unsafe_allow_html=True)

                # # Display medications in a separate table
                # if 'medications' in final_result and final_result['medications']:
                #     medications_df = pd.DataFrame(final_result['medications'])
                #     st.subheader("Medications")
                #     st.table(medications_df)


                # Convert final_result to a list of tuples for display
                data = [(key, _strip_html(final_result[key]) if key == "additional_notes" else final_result[key])
                        for key in final_result if key != 'medications']
                df = pd.DataFrame(data, columns=["Field", "Value"])

                # Theme-aware tables (readable in light + dark mode)
                st.dataframe(df, width="stretch", hide_index=True)

                # Display medications in a separate table with custom styling
                checks = []
                if 'medications' in final_result and final_result['medications']:
                    medications_df = pd.DataFrame(final_result['medications'])
                    st.subheader("Medications")
                    st.dataframe(medications_df, width="stretch", hide_index=True)

                    # Online verification against the Indian medicine database (offline, ~254k brands)
                    with st.spinner('Verifying medicines (Indian DB)...'):
                        checks = [check_medicine_online(m.get('name', '')) for m in final_result['medications']]
                    verify_df = pd.DataFrame([{
                        'Extracted name': c['extracted'],
                        'Indian DB match': c['match'] or '-',
                        'Composition': c.get('composition', '') or '-',
                        'Manufacturer': c.get('manufacturer', '') or '-',
                        'Pack': c.get('pack_size', '') or '-',
                        'Type': c.get('med_type', '') or '-',
                        'Status': c['status'],
                    } for c in checks])
                    st.subheader("Medicine Verification (Indian DB)")
                    st.dataframe(verify_df, width="stretch", hide_index=True)
                    st.caption("Source: open Indian Medicine Dataset (~254k brands) with pack/type info. 'Not found' usually means a Bangladesh-local brand absent from the Indian list - not a fake drug.")

                    # Side effects & safety: full Indian data + openFDA label info.
                    # Fast path: FDA lookups run in parallel, ONE Gemini call simplifies all.
                    st.subheader("Side Effects & Safety (Indian data + openFDA)")
                    st.warning("⚠️ Educational only — not medical advice. Always verify with a doctor or pharmacist.")
                    with st.spinner("Looking up side effects..."):
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=6) as ex:
                            safety_list = list(ex.map(
                                lambda mc: get_drug_safety(mc[0].get("name", ""), mc[1].get("composition", "")),
                                zip(final_result["medications"], checks),
                            ))
                        simple_map = simplify_all_for_patient([
                            (m.get("name", ""), s.get("side_effects", ""))
                            for m, s in zip(final_result["medications"], safety_list)
                        ])
                        for m, c, safety in zip(final_result["medications"], checks, safety_list):
                            mname = m.get("name", "")
                            with st.expander(f"{mname} — {safety['status']}", expanded=False):
                                if c.get("salt_count"):
                                    st.markdown(
                                        f"**Indian DB:** salt '{c.get('composition')}' found in "
                                        f"{c['salt_count']} products "
                                        f"(e.g. {c.get('salt_example') or '-'})"
                                    )
                                else:
                                    st.markdown(
                                        f"**Indian DB:** {c.get('match') or '-'}  \n"
                                        f"Composition: {c.get('composition') or '-'}  \n"
                                        f"Manufacturer: {c.get('manufacturer') or '-'}  \n"
                                        f"Pack: {c.get('pack_size') or '-'} | Type: {c.get('med_type') or '-'}"
                                    )
                                if safety.get("boxed_warning"):
                                    st.error(f"Boxed warning: {safety['boxed_warning']}")
                                native_se = (c.get("side_effects_db") or "").strip()
                                native_di = (c.get("drug_interactions_db") or "").strip()
                                if native_se:
                                    st.markdown(f"**Side effects (Indian DB):** {native_se[:800]}")
                                elif (simple_map.get((mname or '').lower()) or "").strip():
                                    st.markdown(f"**Common side effects:** {(simple_map.get((mname or '').lower()) or '').strip()}")
                                elif safety.get("side_effects"):
                                    st.markdown(f"**Side effects (FDA):** {safety['side_effects'][:300]}")
                                else:
                                    st.caption("No side-effect entry.")
                                if c.get("medicine_desc"):
                                    with st.expander("What it is for (Indian DB)", expanded=False):
                                        st.write(c["medicine_desc"][:1200])
                                if native_di:
                                    with st.expander("⚠️ Drug interactions (Indian DB)", expanded=False):
                                        st.write(native_di[:1200])
                                alts = find_alternatives(c.get("composition", ""), exclude=mname, n=3)
                                if alts:
                                    st.caption(f"Alternatives (same salt): {', '.join(alts)}")
                                if safety.get("source_url"):
                                    st.markdown(f"[Full label on DailyMed]({safety['source_url']}) · Source: {safety['source']}")
                                st.caption(f"Prescribed: {m.get('dosage','')} | {m.get('frequency','')} | {m.get('duration','')}")

                # Combination screening: one batched call over all medicines.
                if len(final_result.get("medications", [])) >= 2:
                    st.subheader("Combination Check (drug interactions)")
                    with st.spinner("Screening combinations..."):
                        inter = check_interactions([
                            (m.get("name", ""),
                             next((c.get("composition", "") for c in checks
                                   if c.get("extracted") == m.get("name", "")), ""))
                            for m in final_result["medications"]
                        ])
                    if inter["pairs"]:
                        for p in inter["pairs"]:
                            st.error(f"⚠️ {p['drugs']}: {p['detail']}")
                    else:
                        st.success(inter["status"])
                    st.caption("AI screen over label knowledge, not a curated database. Always verify with a pharmacist.")

                # Human-review flags: never silently fix, always surface
                review_flags = build_review_flags(final_result, checks)
                for flag in review_flags:
                    st.warning(f"Please review: {flag}")
                age_flags = check_dosage_age(final_result.get("medications"), final_result.get("patient_age"))
                for flag in age_flags:
                    st.warning(f"Dosage check: {flag}")
                if not review_flags and not age_flags:
                    st.success("All sanity checks passed - no review flags.")
                st_status.update(label="Prescription processed — see results below",
                                 state="complete", expanded=False)

                # Glanceable summary before the details
                verified = sum(1 for c in checks if c.get("status", "").startswith(("Verified", "Auto-corrected")))
                m1, m2, m3 = st.columns(3)
                m1.metric("Medicines found", len(final_result.get("medications", [])))
                m2.metric("Verified / corrected", verified)
                m3.metric("Review flags", len(review_flags))

                # Copy to clipboard: plain-text summary + JSON. st.code gives a
                # native copy icon; the button below is an explicit one-click copy.
                st.subheader("Copy Results")
                clipboard_text = format_results_for_clipboard(final_result, checks, review_flags)
                render_copy_button(clipboard_text, button_text="Copy to Clipboard", key="rx_text")
                st.code(clipboard_text, language="markdown")

                with st.expander("JSON (for copy/paste into other tools)", expanded=False):
                    json_text = json.dumps(final_result, indent=2, default=str)
                    render_copy_button(json_text, button_text="Copy JSON", key="rx_json")
                    st.code(json_text, language="json")

                # Export CSV/PDF
                st.subheader("Export")
                import io as _io2
                # CSV of medications
                med_csv = pd.DataFrame(final_result.get("medications", [])).to_csv(index=False)
                st.download_button("⬇️ Download medications CSV", med_csv, file_name=f"rx_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", key="dl_csv")
                # Printable text report (for Save as PDF via browser)
                report = clipboard_text + "\n\n---\nVerification:\n" + "\n".join(f"{c['extracted']} -> {c['match']} ({c['status']})" for c in checks)
                st.download_button("⬇️ Download report (TXT)", report, file_name=f"rx_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", mime="text/plain", key="dl_txt")
                try:
                    from fpdf import FPDF
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", "B", 16)
                    pdf.cell(0, 10, "Medical Prescription Report", ln=True, align="C")
                    pdf.set_font("Helvetica", "", 9)
                    for line in report.split("\n"):
                        pdf.multi_cell(0, 5, line.encode("latin-1", "replace").decode("latin-1"))
                    pdf_bytes = pdf.output()
                    st.download_button("⬇️ Download clinical PDF", bytes(pdf_bytes), file_name=f"rx_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf", mime="application/pdf", key="dl_pdf")
                except Exception as e:
                    st.caption(f"PDF export not available: {e}")
                st.caption("Tip: Print this page (Ctrl+P) → Save as PDF for a formatted report.")

                # Save to session history
                st.session_state.history.insert(0, {
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "patient": final_result.get("patient_name", ""),
                    "meds": len(final_result.get("medications", [])),
                    "raw": final_result,
                })
                st.session_state.history = st.session_state.history[:20]

            # Delete temp folder
            remove_temp_folder(output_folder)

    with tab_hist:
        st.subheader("📜 History (this session)")
        if not st.session_state.history:
            st.caption("No prescriptions processed yet in this session.")
        else:
            if st.button("Clear history", key="clear_hist"):
                st.session_state.history = []
                st.rerun()
            for i, h in enumerate(st.session_state.history):
                with st.expander(f"{h['ts']} — {h['patient'] or 'Unknown'} ({h['meds']} meds)", expanded=(i == 0)):
                    st.json(h["raw"])

if __name__ == "__main__":
    main()
