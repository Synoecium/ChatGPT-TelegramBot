import base64, textwrap, time, openai, os, io
from PIL import Image
from typing import Tuple

DETAIL_THRESHOLD = 512
MAX_SIZE = 1024

def create_image_content(image_bytes: bytes) -> Tuple[dict, str]:
    
    image_base64, detail, info_message = process_image_as_bytes(image_bytes)
    content_image = {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{image_base64}", "detail": detail}
    }
    return content_image, info_message


# ======================================================================================================
# Private functions
# ======================================================================================================
        
def process_image_as_bytes(image_bytes: bytes) -> Tuple[str, str, str]:
    """
    Process an image as bytes, encoding it in base64. If the image is a PNG and smaller than max_size,
    it encodes the original. Otherwise, it resizes and converts the image to PNG before encoding.

    Parameters:
        image (bytes): Image.
        max_size (int): The maximum width and height allowed for the image.

    Returns:
        Tuple[str, int]: A tuple containing the base64-encoded image and the size of the largest dimension.
    """
    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size
    mimetype = image.get_format_mimetype()
    if not (width <= MAX_SIZE and height <= MAX_SIZE):
        resized_image = resize_image(image, MAX_SIZE)
        width, height = resized_image.size
        image = resized_image

    if mimetype != "image/png":  
        png_image = convert_to_png(image)
        image = png_image

    encoded_image = base64.b64encode(image).decode('utf-8')   
    maxdim = max(width, height)
    detail = "low" if maxdim < DETAIL_THRESHOLD else "high"
    info_message = f"image: {width}x{height}, detail: {detail}"
    return (encoded_image, detail, info_message)

def resize_image(image: Image.Image, max_dimension: int) -> Image.Image:
    """
    Resize a PIL image to ensure that its largest dimension does not exceed max_size.

    Parameters:
        image (Image.Image): The PIL image to resize.
        max_size (int): The maximum size for the largest dimension.

    Returns:
        Image.Image: The resized image.
    """
    width, height = image.size
    
    
    # Check if the image has a palette and convert it to true color mode
    if image.mode == "P":
        if "transparency" in image.info:
            image = image.convert("RGBA")
        else:
            image = image.convert("RGB")

    if width > max_dimension or height > max_dimension:
        if width > height:
            new_width = max_dimension
            new_height = int(height * (max_dimension / width))
        else:
            new_height = max_dimension
            new_width = int(width * (max_dimension / height))
        image = image.resize((new_width, new_height), Image.LANCZOS)
        
        timestamp = time.time()

    return image

def convert_to_png(image: Image.Image) -> bytes:
    """
    Convert a PIL Image to PNG format.

    Parameters:
        image (Image.Image): The PIL image to convert.

    Returns:
        bytes: The image in PNG format as a byte array.
    """
    with io.BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


