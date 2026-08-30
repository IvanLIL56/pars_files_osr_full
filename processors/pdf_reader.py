"""PDF reader module.

Reads text from PDF files using PyMuPDF (fitz).
Determines if PDF has text layer or requires OCR.
"""

from pathlib import Path
from typing import Dict, Any

import fitz  # PyMuPDF

from config import settings
from utils.logger import setup_logger


logger = setup_logger(__name__)


def type_pdf(file_path: Path) -> str:
    """Determine if PDF has readable text layer.
    
    Args:
        file_path: Path to PDF file
    
    Returns:
        'read' if text layer exists, 'no_read' otherwise
    """
    try:
        pdf = fitz.open(file_path)
        words = pdf[0].get_text().strip()
        pdf.close()
        
        return 'read' if words else 'no_read'
    except Exception as e:
        logger.error(f"Error checking PDF type: {e}")
        return 'no_read'


def process_readable_pdf(file_path: Path, file_id: str) -> Dict[str, Any]:
    """Process PDF with text layer.
    
    Extracts text directly from PDF pages.
    
    Args:
        file_path: Path to PDF file
        file_id: File identifier
    
    Returns:
        Dictionary with extracted text and metadata
    """
    try:
        doc = fitz.open(file_path)
        page_count = len(doc)
        full_text = ''
        
        for page in doc:
            full_text += page.get_text()
        
        doc.close()
        
        return {
            'id': file_id,
            'type_read': 'pdf',
            'status': 'done',
            'page_count': page_count,
            'char_count': len(full_text),
            'image_quality': None,
            'full_text': full_text
        }
    
    except Exception as e:
        logger.error(f"Error processing readable PDF {file_path}: {e}")
        return {
            'id': file_id,
            'status': f'error: {e}',
            'type_read': 'pdf',
            'page_count': 0,
            'char_count': 0,
            'image_quality': None,
            'full_text': f"[Ошибка: {e}]"
        }


def process_pdf_osr(file_path: Path, file_id: str, dpi: int = None) -> Dict[str, Any]:
    """Process scanned PDF with OCR.
    
    Renders each page as image and applies OCR.
    
    Args:
        file_path: Path to PDF file
        file_id: File identifier
        dpi: Rendering DPI (default from config)
    
    Returns:
        Dictionary with OCR text and quality metrics
    """
    if dpi is None:
        dpi = settings.ocr.OCR_DPI
    
    doc = None
    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count
        all_text = []
        qualities = []
        total_chars = 0
        
        for i in range(page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=dpi)
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Preprocess and OCR
            proc = preprocess_for_ocr(img)
            quality = analyze_image_quality(img)
            qualities.append(quality)
            
            page_text = pytesseract.image_to_string(
                proc, 
                lang=settings.ocr.TESS_LANG, 
                config=settings.ocr.TESS_CONFIG
            )
            
            all_text.append(f"--- Страница {i+1} ---\n{page_text}")
            total_chars += len(page_text)
            
            # Free memory
            pix = None
            img = None
            proc = None
            page = None
        
        doc.close()
        doc = None
        
        # Compile quality metrics
        avg_brightness = sum(q['mean_brightness'] for q in qualities) / len(qualities)
        avg_darkness = sum(q['darkness_score'] for q in qualities) / len(qualities)
        avg_dark_ratio = sum(q['dark_pixels_ratio'] for q in qualities) / len(qualities)
        
        parts = [
            f"pdf|{page_count}p|{dpi}dpi|"
            f"avg_brightness={round(avg_brightness,1)}|"
            f"avg_darkness={round(avg_darkness,3)}|"
            f"avg_dark_ratio={round(avg_dark_ratio,3)}"
        ]
        
        for idx, q in enumerate(qualities, 1):
            parts.append(
                f"p{idx}:br={q['mean_brightness']},"
                f"dk={q['darkness_score']},"
                f"lb={q['label']}"
            )
        
        return {
            'id': file_id,
            'status': 'done',
            'type_read': 'osr',
            'page_count': page_count,
            'char_count': total_chars,
            'image_quality': "; ".join(parts),
            'full_text': "\n\n".join(all_text)
        }
    
    except Exception as e:
        logger.error(f"Error OCR PDF {file_path}: {e}")
        if doc:
            doc.close()
        return {
            'id': file_id,
            'status': f'error: {e}',
            'type_read': 'osr',
            'page_count': 0,
            'char_count': 0,
            'image_quality': f'error: {e}',
            'full_text': f'[Ошибка: {e}]'
        }


def preprocess_for_ocr(img, min_width: int = None) -> Any:
    """Preprocess image for OCR.
    
    Applies minimal preprocessing that helps Tesseract:
    - Grayscale conversion
    - Resolution scaling
    - Light denoising
    - Selective sharpening
    
    Args:
        img: PIL Image
        min_width: Minimum width for scaling
    
    Returns:
        Preprocessed PIL Image
    """
    from PIL import Image, ImageFilter, ImageStat
    
    if min_width is None:
        min_width = settings.ocr.MIN_IMAGE_WIDTH
    
    # 1. Grayscale
    img = img.convert('L')
    
    # 2. Scale up if too small
    w, h = img.size
    if w < min_width:
        scale = 2.0 if w < 1500 else 1.5
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    
    # 3. Light denoise (3x3 median filter)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    
    # 4. Selective sharpening based on brightness
    stat = ImageStat.Stat(img)
    brightness = stat.mean[0]
    
    if brightness < 100 or brightness > 220:
        # Too dark or overexposed - add sharpening
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=3))
    
    return img


def analyze_image_quality(img) -> Dict[str, Any]:
    """Analyze image quality for OCR.
    
    Computes metrics like brightness, darkness, etc.
    
    Args:
        img: PIL Image (grayscale)
    
    Returns:
        Dictionary with quality metrics
    """
    from PIL import ImageStat
    
    gray = img.convert('L')
    stat = ImageStat.Stat(gray)
    mean_brightness = stat.mean[0]
    
    hist = gray.histogram()
    total = sum(hist) or 1
    dark_ratio = sum(hist[:50]) / total
    darkness_score = 1.0 - (mean_brightness / 255.0)
    
    issues = []
    if mean_brightness < 50:
        issues.append("critical_dark")
    elif mean_brightness < 85:
        issues.append("very_dark")
    elif mean_brightness < 120:
        issues.append("dark")
    
    label = "poor" if issues else ("fair" if mean_brightness < 150 else "good")
    
    return {
        'mean_brightness': round(mean_brightness, 1),
        'darkness_score': round(darkness_score, 3),
        'dark_pixels_ratio': round(dark_ratio, 3),
        'label': label,
        'issues': '; '.join(issues) if issues else 'none'
    }


# Import pytesseract here to avoid circular imports
try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None
    logger.warning("pytesseract or PIL not available - OCR disabled")
