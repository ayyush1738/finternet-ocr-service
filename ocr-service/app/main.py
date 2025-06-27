from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
import pytesseract
from pdf2image import convert_from_bytes
import base64
import logging
import traceback
import requests
import tempfile
import os
import re


logging.basicConfig(level=logging.INFO)
app = FastAPI()

class OCRRequest(BaseModel):
    file_b64: str

TOTAL_KEYWORDS = [
    "total due", "total amount", "net amount", "amount payable",
    "invoice total", "total sum", "balance due", "total to pay",
    "grand total", "amount to pay", "net total"
]

def extract_likely_total(text: str) -> str:
    candidates = []

    for line in text.splitlines():
        lower_line = line.lower()
        # Look for "total" variants manually
        if "total" in lower_line or any(k in lower_line for k in TOTAL_KEYWORDS):
            print(f"🔍 Matched line: {line}")
            # Try to match INR, Rs., ₹, or plain float
            matches = re.findall(r"(?:rs\.?|inr|₹|$)?\s*([\d,]+\.\d{2})", lower_line)
            for amt in matches:
                try:
                    candidates.append(float(amt.replace(",", "")))
                except:
                    continue

    if not candidates:
        # Fallback: try getting the largest float-like value in entire doc
        matches = re.findall(r"([\d,]+\.\d{2})", text)
        for amt in matches:
            try:
                candidates.append(float(amt.replace(",", "")))
            except:
                continue

    if candidates:
        max_val = max(candidates)
        print(f"✅ Candidates: {candidates}, Max: {max_val}")
        return f"{max_val:.2f}"

    return "Not Found"



@app.post("/analyze")
async def analyze(req: OCRRequest):
    try:
        # Decode base64 PDF content
        content = base64.b64decode(req.file_b64)

        # Convert PDF to images for OCR
        images = convert_from_bytes(content)
        if not images:
            raise ValueError("No pages found in the PDF.")

        # Run OCR on all pages
        text = "".join([pytesseract.image_to_string(img) for img in images])
        if not text.strip():
            raise ValueError("OCR did not extract any text.")

        # Extract total amount from text
        total_amount = extract_likely_total(text)

        # Save PDF and upload to IPFS
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(content)
            temp_pdf_path = temp_pdf.name

        with open(temp_pdf_path, 'rb') as f:
            response = requests.post('http://127.0.0.1:5001/api/v0/add', files={'file': f})
            response.raise_for_status()
            ipfs_result = response.json()
            cid = ipfs_result['Hash']
            print("✅ Uploaded to IPFS:", cid)

        os.remove(temp_pdf_path)
        

        return {
            "text": text,
            "total_amount": total_amount,
            "cid": cid
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logging.error(f"OCR failed: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OCR error: {str(e)}"
        )
