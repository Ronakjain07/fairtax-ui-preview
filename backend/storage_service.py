import os, uuid
from werkzeug.utils import secure_filename
from config import Config

ALLOWED = {"pdf", "jpg", "jpeg", "png"}

def save_file(file_storage, phone):
    """Save uploaded file locally, return public URL."""
    os.makedirs(Config.UPLOAD_DIR, exist_ok=True)
    user_dir = os.path.join(Config.UPLOAD_DIR, str(phone or "anon"))
    os.makedirs(user_dir, exist_ok=True)

    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED:
        return None
    fname = f"{uuid.uuid4().hex[:8]}_{secure_filename(file_storage.filename)}"
    fpath = os.path.join(user_dir, fname)
    file_storage.save(fpath)
    url = f"{Config.PUBLIC_BASE_URL}/uploads/{phone}/{fname}"
    return url