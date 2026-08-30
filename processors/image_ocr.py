"""Image OCR module.

Performs optical character recognition on image files.
Supports multiple image formats with preprocessing.
"""

from pathlib import Path
from typing import Dict, Any

from PIL import Image, ImageFilter, ImageStat
import pytesseract

from config import settings
from utils.logger import setup_logger


logger = setup_logger(__name__)


def process_image_osr(file_path: Path, file_id: str) -> Dict[str, Any]:
    """Perform OCR on image file.
    
    Args:
        file_path: Path to image file
        file_id: File identifier
    
    Returns:
        Dictionary with OCR text and quality metrics
    """
    try:
        img = Image.open(file_path)
        orig_size = img.size
        
        # Preprocess
        proc = preprocess_for_ocr(img)
        quality = analyze_image_quality(img)
        
        # OCR
        text = pytesseract.image_to_string(
            proc, 
            lang=settings.ocr.TESS_LANG, 
            config=settings.ocr.TESS_CONFIG
        )
        
        # Format quality string
        quality_str = (
            f"img|{orig_size[0]}x{orig_size[1]}|"
            f"proc={proc.size[0]}x{proc.size[1]}|"
            f"brightness={quality['mean_brightness']}|"
            f"darkness={quality['darkness_score']}|"
            f"dark_ratio={quality['dark_pixels_ratio']}|"
            f"label={quality['label']}|"
            f"issues={quality['issues']}"
        )
        
        return {
            'id': file_id,
            'status': 'done',
            'type_read': 'osr',
            'page_count': 1,
            'char_count': len(text),
            'image_quality': quality_str,
            'full_text': text
        }
    
    except Exception as e:
        logger.error(f"Error OCR image {file_path}: {e}")
        return {
            'id': file_id,
            'status': f'error: {e}',
            'type_read': 'osr',
            'page_count': 0,
            'char_count': 0,
            'image_quality': f'error: {e}',
            'full_text': f'[Ошибка: {e}]'
        }


def preprocess_for_ocr(img: Image.Image, min_width: int = None) -> Image.Image:
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


def analyze_image_quality(img: Image.Image) -> Dict[str, Any]:
    """Analyze image quality for OCR.
    
    Computes metrics like brightness, darkness, etc.
    
    Args:
        img: PIL Image
    
    Returns:
        Dictionary with quality metrics
    """
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
