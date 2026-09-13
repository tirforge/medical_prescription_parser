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
from indian_db import verify_medicine as check_medicine_online
from drug_info import get_drug_safety, simplify_all_for_patient

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
st.set_page_config(layout="wide")

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

# Initialize session state
session_state = st.session_state
if 'uploaded_file' not in session_state:
    session_state.uploaded_file = None

# Patterns that usually deserve a human second look.
AMBIGUOUS_SUFFIX = re.compile(r'-(D|DS|Plus|Forte|SR|XR|CR|LS|MR|M|H|AM|HT|LD|HD|P)\b', re.I)
INITIAL_ONLY = re.compile(r'\b[A-Z]\.')

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
    st.title('Medical Prescription Parsing')
    global parser
    parser = JsonOutputParser(pydantic_object=PrescriptionInformations)
    #st.header('Prescription Processing')
    uploaded_files = st.file_uploader(
        "Upload Prescription image(s) — multi-page supported",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

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

    inputs: list = []  # [(filename, bytes)]
    for f in uploaded_files or []:
        inputs.append((f.name, f.getvalue()))
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

        with st.spinner('Processing Prescription...'):
            final_result = get_prescription_informations(model_paths)           
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


            # Convert final_result to a list of tuples for DataFrame creation
            data = [(key, final_result[key]) for key in final_result if key != 'medications']
            df = pd.DataFrame(data, columns=["Field", "Value"])

            # Display the DataFrame with custom styling
            st.write(df.to_html(classes='custom-table', index=False, escape=False), unsafe_allow_html=True)

            # Display medications in a separate table with custom styling
            checks = []
            if 'medications' in final_result and final_result['medications']:
                medications_df = pd.DataFrame(final_result['medications'])
                st.subheader("Medications")
                st.write(medications_df.to_html(classes='custom-table', index=False, escape=False), unsafe_allow_html=True)

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
                st.write(verify_df.to_html(classes='custom-table', index=False, escape=False), unsafe_allow_html=True)
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
                            simple = (simple_map.get((mname or '').lower()) or "").strip()
                            if simple:
                                st.markdown(f"**Common side effects:** {simple}")
                            elif safety.get("side_effects"):
                                st.markdown(f"**Side effects:** {safety['side_effects'][:300]}")
                            else:
                                st.caption("No FDA side-effect entry (common for India-local brands).")
                            if safety.get("source_url"):
                                st.markdown(f"[Full label on DailyMed]({safety['source_url']}) · Source: {safety['source']}")
                            st.caption(f"Prescribed: {m.get('dosage','')} | {m.get('frequency','')} | {m.get('duration','')}")

            # Human-review flags: never silently fix, always surface
            review_flags = build_review_flags(final_result, checks)
            for flag in review_flags:
                st.warning(f"Please review: {flag}")
            if not review_flags:
                st.success("All sanity checks passed - no review flags.")

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

        # Delete temp folder
        remove_temp_folder(output_folder)

if __name__ == "__main__":
    main()
