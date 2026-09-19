from fastapi import FastAPI, HTTPException
import httpx
import os
import json
import urllib.parse
from pydantic import BaseModel
from typing import Optional

class SavePinRequest(BaseModel):
    pin_id: str
    board_id: str

app = FastAPI(title="Pinspark Bypass Backend")

# 1. Secrets Setup
raw_csrf = os.environ.get("PIN_CSRF_TOKEN", "")
raw_cookie = os.environ.get("PIN_COOKIE", "")
clean_csrf = raw_csrf.strip()
clean_cookie = raw_cookie.strip()

# 2. Global Headers
HEADERS = {
    "authority": "www.pinterest.com",
    "accept": "application/json, text/javascript, */*, q=0.01",
    "x-requested-with": "XMLHttpRequest",
    "x-csrftoken": clean_csrf,
    "cookie": clean_cookie,
    "referer": "https://www.pinterest.com/sparkling_gyan/",
    "origin": "https://www.pinterest.com",
    "x-pinterest-appstate": "active",
    "x-pinterest-pws-handler": "www/sparkling_gyan.js",
    "x-pinterest-source-url": "/sparkling_gyan/",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"
}

def verify_secrets():
    if not clean_cookie or not clean_csrf:
        print("Missing Secrets!")
        raise HTTPException(status_code=500, detail="Cookie or CSRF missing in Environment Variables")

# ==========================================
# REFACTORED: Centralized Pin Parser Logic
# ==========================================
def extract_video_url(v_list: dict) -> Optional[str]:
    if not v_list:
        return None
    for q in ["V_1080P", "V_720P", "v_720p", "V_480P", "v_480p", "V_HLSV3_MOBILE"]:
        v_data = v_list.get(q) or {}
        if v_data.get("url") and ".mp4" in v_data.get("url"):
            return v_data.get("url")
    # Fallback without .mp4 check
    for q in ["V_1080P", "V_720P", "v_720p", "V_480P", "v_480p", "V_HLSV3_MOBILE"]:
        v_data = v_list.get(q) or {}
        if v_data.get("url"):
            return v_data.get("url")
    return None

def parse_pin_data(pin: dict) -> Optional[dict]:
    """Extracts standardized data from a raw Pinterest pin dictionary."""
    if not pin or not isinstance(pin, dict):
        return None
    
    # Skip ads or non-pin items (important for home/search feeds)
    if pin.get("type") and pin.get("type") != "pin":
        return None

    is_video = pin.get("is_video", False) or pin.get("is_native_video", False)
    media_url = None
    
    images = pin.get("images") or {}
    orig_img = images.get("orig") or {}
    fallback_img = images.get("736x") or {}
    thumbnail_url = orig_img.get("url") or fallback_img.get("url")

    videos = pin.get("videos") or {}
    if videos and "video_list" in videos:
        media_url = extract_video_url(videos.get("video_list") or {})
        if media_url:
            is_video = True

    # Story Pins / Carousel Check
    if not media_url:
        story_data = pin.get("story_pin_data") or {}
        for page in (story_data.get("pages") or []):
            if not page:
                continue
            for block in (page.get("blocks") or []):
                if not block:
                    continue
                video_block = block.get("video") or {}
                if "video_list" in video_block:
                    media_url = extract_video_url(video_block.get("video_list") or {})
                    if media_url:
                        is_video = True
                        break
            if media_url:
                break

    # Fallback trick for standard pins that are actually videos
    if not media_url and is_video and thumbnail_url:
        if "i.pinimg.com/originals" in thumbnail_url:
            media_url = thumbnail_url.replace("i.pinimg.com/originals", "v1.pinimg.com/videos/mc/720p")
            media_url = media_url.replace(".jpg", ".mp4").replace(".png", ".mp4")
            is_video = True

    if not media_url:
        is_video = False
        media_url = thumbnail_url

    title = pin.get("grid_title", "") or pin.get("title", "") or pin.get("description", "")

    if media_url and thumbnail_url:
        return {
            "id": pin.get("id"),
            "media_url": media_url,
            "thumbnail_url": thumbnail_url,
            "is_video": is_video,
            "title": title
        }
    return None

# ==========================================
# ENDPOINTS
# ==========================================

@app.get("/api/my-boards")
async def get_boards_internal():
    verify_secrets()
    url = "https://www.pinterest.com/resource/BoardsResource/get/"
    params = {
        "source_url": "/sparkling_gyan/",
        "data": '{"options":{"username":"sparkling_gyan","privacy_filter":"all","sort":"alphabetical"},"context":{}}'
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=HEADERS, params=params)
            response.raise_for_status()
            data = response.json()
            boards_data = data.get("resource_response", {}).get("data") or []
            formatted_boards = []
            for board in boards_data:
                if not board:
                    continue
                thumbnails = []
                if board.get("pin_thumbnail_urls"):
                    thumbnails = board.get("pin_thumbnail_urls")
                elif board.get("cover_images"):
                    for img_obj in board.get("cover_images"):
                        if isinstance(img_obj, dict) and img_obj.get("url"):
                            thumbnails.append(img_obj.get("url"))
                elif board.get("image_cover_url"):
                    thumbnails = [board.get("image_cover_url")]
                elif board.get("images"):
                    imgs = board.get("images")
                    best_img = imgs.get("170x170") or imgs.get("orig") or imgs.get("736x") or {}
                    if best_img.get("url"):
                        thumbnails = [best_img.get("url")]
                if len(thumbnails) > 3:
                    thumbnails = thumbnails[:3]
                formatted_boards.append({
                    "id": board.get("id"),
                    "name": board.get("name"),
                    "description": board.get("description", "No description."),
                    "thumbnails": thumbnails
                })
            return {"items": formatted_boards}
        except Exception as e:
            print(f"Board Fetch Error: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching boards")

@app.get("/api/boards/{board_id}/pins")
async def get_board_pins(board_id: str, bookmark: Optional[str] = None):
    verify_secrets()
    url = "https://www.pinterest.com/resource/BoardFeedResource/get/"
    options = {"board_id": board_id}
    if bookmark:
        options["bookmarks"] = [bookmark]
    params = {
        "source_url": "/sparkling_gyan/",
        "data": json.dumps({"options": options, "context": {}})
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=HEADERS, params=params)
            response.raise_for_status()
            data = response.json()
            next_bookmark = data.get("resource_response", {}).get("bookmark", "-end-")
            pins_data = data.get("resource_response", {}).get("data") or []
            formatted_pins = [p for p in (parse_pin_data(pin) for pin in pins_data) if p is not None]
            return {
                "items": formatted_pins,
                "bookmark": next_bookmark if next_bookmark != "-end-" else None
            }
        except Exception as e:
            print(f"Pin Fetch Error: {str(e)}")
            raise HTTPException(status_code=500, detail="Error processing pins data")

@app.get("/api/home")
async def get_home_feed(bookmark: Optional[str] = None):
    verify_secrets()
    url = "https://www.pinterest.com/resource/UserHomefeedResource/get/"
    options = {
        "field_set_key": "mobile_grid_item",
        "prepend": False,
        "first_page_size": "25",
        "page_size": "10",
        "in_local_navigation": True,
        "static_feed": False
    }
    if bookmark:
        options["bookmarks"] = [bookmark]
    params = {
        "source_url": "/",
        "data": json.dumps({"options": options, "context": {}})
    }
    custom_headers = HEADERS.copy()
    custom_headers.update({
        "referer": "https://www.pinterest.com/",
        "x-pinterest-source-url": "/",
        "x-pinterest-pws-handler": "www/index.js"
    })
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=custom_headers, params=params)
            response.raise_for_status()
            data = response.json()
            next_bookmark = data.get("resource_response", {}).get("bookmark", "-end-")
            pins_data = data.get("resource_response", {}).get("data") or []
            formatted_pins = [p for p in (parse_pin_data(pin) for pin in pins_data) if p is not None]
            return {
                "items": formatted_pins,
                "bookmark": next_bookmark if next_bookmark != "-end-" else None
            }
        except Exception as e:
            print(f"Home Feed Fetch Error: {str(e)}")
            raise HTTPException(status_code=500, detail="Error processing home feed")

@app.get("/api/search")
async def get_search_results(q: str, bookmark: Optional[str] = None):
    verify_secrets()
    if not q:
        raise HTTPException(status_code=400, detail="Search query is required")
    url = "https://www.pinterest.com/resource/BaseSearchResource/get/"
    options = {
        "query": q,
        "scope": "pins",
        "appliedProductFilters": "---",
        "seoDrawerEnabled": False,
        "auto_correction_disabled": False,
        "filter_genai": False,
        "static_feed": False,
        "rs": "rs"
    }
    if bookmark:
        options["bookmarks"] = [bookmark]
    source_url = f"/search/pins/?q={urllib.parse.quote(q)}&rs=rs"
    params = {
        "source_url": source_url,
        "data": json.dumps({"options": options, "context": {}})
    }
    custom_headers = HEADERS.copy()
    custom_headers.update({
        "referer": "https://www.pinterest.com/",
        "x-pinterest-source-url": source_url,
        "x-pinterest-pws-handler": "www/search/[scope].js"
    })
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=custom_headers, params=params)
            response.raise_for_status()
            data = response.json()
            next_bookmark = data.get("resource_response", {}).get("bookmark", "-end-")
            res_data = data.get("resource_response", {}).get("data") or {}
            pins_data = res_data if isinstance(res_data, list) else (res_data.get("results") or [])
            formatted_pins = [p for p in (parse_pin_data(pin) for pin in pins_data) if p is not None]
            return {
                "items": formatted_pins,
                "bookmark": next_bookmark if next_bookmark != "-end-" else None
            }
        except Exception as e:
            print(f"Search Fetch Error: {str(e)}")
            raise HTTPException(status_code=500, detail="Error processing search results")

@app.post("/api/save-pin")
async def save_pin(req: SavePinRequest):
    verify_secrets()
    url = "https://www.pinterest.com/resource/RepinResource/create/"
    payload = {
        "source_url": f"/pin/{req.pin_id}/repin/",
        "data": json.dumps({
            "options": {"pin_id": req.pin_id, "board_id": req.board_id},
            "context": {}
        })
    }
    encoded_data = urllib.parse.urlencode(payload)
    custom_headers = HEADERS.copy()
    custom_headers.update({
        "content-type": "application/x-www-form-urlencoded",
        "x-pinterest-source-url": f"/pin/{req.pin_id}/repin/",
        "x-pinterest-pws-handler": "www/pin/[id]/repin.js",
        "referer": "https://www.pinterest.com/"
    })
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, headers=custom_headers, content=encoded_data)
            res.raise_for_status()
            return {"status": "success", "message": "Pin saved successfully!"}
        except Exception as e:
            print("Save Pin Error:", e)
            raise HTTPException(status_code=500, detail="Internal Error while saving pin")
