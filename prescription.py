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
import pandas as pd
import shutil
from indian_db import verify_medicine as check_medicine_online

os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY or os.environ.get("GOOGLE_API_KEY", "")
# Free vision model valid Sept 2026: gemini-2.5-flash (2.0-flash retired June 1, 2026).
# Lite fallback: gemini-2.5-flash-lite. Note 2.5-flash retires Oct 20, 2026 -> then gemini-3.5-flash.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
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
    return msg.content

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
        if c.get("status", "").startswith(("Suggestion", "Not found")):
            flags.append(f"'{nm}': {c['status']}.")
    return flags


def main():
    st.title('Medical Prescription Parsing')
    global parser
    parser = JsonOutputParser(pydantic_object=PrescriptionInformations)
    #st.header('Prescription Processing')
    uploaded_file = st.file_uploader("Upload a Prescription image", type=["png", "jpg", "jpeg"])
    if uploaded_file is not None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = uploaded_file.name.split('.')[0].replace(' ', '_')
        output_folder = os.path.join(".", f"Check_{filename}_{timestamp}")
        os.makedirs(output_folder, exist_ok=True)

        check_path = os.path.join(output_folder, uploaded_file.name)
        with open(check_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        with st.expander("Prescription Image", expanded=False):
            st.image(uploaded_file, caption='Uploaded Prescription Image.', width='stretch')

        with st.spinner('Processing Prescription...'):  
            final_result = get_prescription_informations([check_path])           
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
                    'Status': c['status'],
                } for c in checks])
                st.subheader("Medicine Verification (Indian DB)")
                st.write(verify_df.to_html(classes='custom-table', index=False, escape=False), unsafe_allow_html=True)
                st.caption("Source: open Indian Medicine Dataset (~254k brands). 'Not found' usually means a Bangladesh-local brand absent from the Indian list - not a fake drug.")

            # Human-review flags: never silently fix, always surface
            review_flags = build_review_flags(final_result, checks)
            for flag in review_flags:
                st.warning(f"Please review: {flag}")
            if not review_flags:
                st.success("All sanity checks passed - no review flags.")

        # Delete temp folder
        remove_temp_folder(output_folder)

if __name__ == "__main__":
    main()
