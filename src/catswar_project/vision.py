from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .screen_state import Marker, ScreenKind, ScreenRecognizer, ScreenState


class VisionError(RuntimeError):
    pass


class OmniParserClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:8000/parse/", *, timeout: float = 120.0,
                 opener: Callable[..., Any] | None = None) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen

    def parse(self, image_path: Path) -> list[dict[str, Any]]:
        import base64

        payload = {"base64_image": base64.b64encode(image_path.read_bytes()).decode("ascii")}
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise VisionError(f"OmniParser request failed: {exc}") from exc
        items = data.get("parsed_content_list", [])
        if not isinstance(items, list):
            raise VisionError("OmniParser response has no parsed_content_list")
        return [item for item in items if isinstance(item, dict)]


class OmniParserRecognizer(ScreenRecognizer):
    """Convert OmniParser OCR/icon output into the project's stable ScreenState API."""

    def __init__(self, client: OmniParserClient, *, min_confidence: float = 0.35,
                 on_parse: Callable[[Path, list[dict[str, Any]]], None] | None = None) -> None:
        self.client = client
        self.min_confidence = min_confidence
        self.on_parse = on_parse

    def recognize(self, image_path: Path | None = None) -> ScreenState:
        if image_path is None:
            return ScreenState(ScreenKind.UNKNOWN, reason="image_path_required")
        try:
            with Image.open(image_path) as image:
                width, height = image.size
                rgb_image = image.convert("RGB")
            parsed = self.client.parse(image_path)
        except (OSError, SyntaxError, ValueError, VisionError) as exc:
            return ScreenState(ScreenKind.UNKNOWN, source_image=image_path, reason=str(exc))
        markers: list[Marker] = []
        texts: list[str] = []
        numeric_candidates: list[tuple[str, tuple[int, int, int, int], float]] = []
        for item in parsed:
            content = str(item.get("content", "")).strip()
            bbox = _bbox(item.get("bbox"), width, height)
            confidence = float(item.get("confidence", item.get("score", 0.75)) or 0.75)
            if not content or bbox is None or confidence < self.min_confidence:
                continue
            texts.append(content)
            marker_name = _marker_name(content)
            center = _center(bbox)
            if content.strip() in {"1", "2", "3"} and center[0] < width * 0.38 and center[1] > height * 0.62:
                marker_name = "own_vehicle_selector"
            if marker_name is None and _looks_like_building_value(content):
                numeric_candidates.append((content, bbox, confidence))
            if marker_name:
                metadata = _metadata(content, marker_name)
                if marker_name == "own_vehicle_selector":
                    metadata["vehicle_index"] = int(content.strip())
                markers.append(Marker(marker_name, confidence, _center(bbox), bbox, metadata))
        # A bare number is not a building marker. It becomes a value only when
        # it is spatially associated with an explicit building label. This
        # prevents home resource counters and gift badges from opening a map.
        buildings = [marker for marker in markers if marker.name == "building" and marker.bbox]
        for content, bbox, confidence in numeric_candidates:
            if not buildings:
                continue
            if _near_building(bbox, buildings, width, height):
                metadata = _metadata(content, "building_value")
                markers.append(Marker("building_value", confidence, _center(bbox), bbox, metadata))
        if self.on_parse is not None:
            self.on_parse(image_path, parsed)
        markers = _annotate_colors(rgb_image, markers)
        markers = _contextualize_markers(texts, markers, width, height)
        rgb_image.close()
        kind, reason = _classify(texts, markers)
        if kind == ScreenKind.UNKNOWN and not markers:
            reason = reason or "no_known_markers"
        return ScreenState(kind, _state_confidence(markers, kind), tuple(markers), image_path, reason)


def _bbox(value: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        values = [float(part) for part in value]
    except (TypeError, ValueError):
        return None
    if max(values) <= 1.01:
        values = [values[0] * width, values[1] * height, values[2] * width, values[3] * height]
    x0, y0, x1, y1 = (max(0, int(v)) for v in values)
    return (min(x0, width), min(y0, height), min(x1, width), min(y1, height))


def _center(bbox: tuple[int, int, int, int]) -> tuple[int, int]:
    return ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)


def _marker_name(content: str) -> str | None:
    normalized = _normalize_text(content)
    exact = {
        "加入": "join_button", "加入城战": "join_button", "加入战斗": "join_button",
        "开始": "loadout_start", "开始战斗吧": "battle_start_confirm",
        "攻击": "attack_button", "防御": "defense_button", "确定": "confirm_button",
        "点击观战": "watch_button", "正在寻找对手": "match_wait",
        "正在寻找对手帮派": "match_wait", "匹配对手": "match_wait",
        "帮派战": "gang_war_entry", "城市之王": "city_war_title_candidate",
        "等待勇士加入": "match_wait", "需要成员": "match_wait",
        "peopleclub": "guild_entry", "peoplepeople": "guild_entry",
        "numerousumerouspeople": "guild_entry",
        "系统": "system_overlay",
        "为你的帮派显示所有这些对手": "opponent_list", "忙碌": "busy_popup",
        "其他玩家战斗中": "busy_popup", "该玩家目前正与其他玩家战斗中": "busy_popup", "维修": "vehicle_repair",
        "正在被攻击": "vehicle_locked", "新的回合已开始": "distraction_popup",
        "帮派排名": "distraction_popup",
        "错误": "distraction_popup", "胜利": "victory", "失败": "defeat",
    }
    if normalized in exact:
        return exact[normalized]
    if "等待勇士加入" in normalized or ("需要" in normalized and "成员" in normalized):
        return "match_wait"
    if normalized == "工":
        return "building"
    if re.fullmatch(r"(?:仓库|船坞|工厂|竞技场|加油站)(?:[0-9一二三四五六])?", normalized):
        return "building"
    if normalized == "选择":
        return "vehicle_target"
    if normalized == "侦察":
        return "scout_button"
    return None


def _normalize_text(content: str) -> str:
    return re.sub(r"[\s\u3000，。！？：；、,.!?;:]+", "", content).lower()


def _looks_like_building_value(content: str) -> bool:
    return bool(re.fullmatch(r"(?:\.)?\d{1,3}", _normalize_text(content)))


def _near_building(
    bbox: tuple[int, int, int, int], buildings: list[Marker], width: int, height: int
) -> bool:
    center = _center(bbox)
    # Resource bars and gift badges occupy the top/bottom chrome; never use
    # those regions as building values even if a building label is nearby.
    if center[1] < int(height * 0.25) or center[1] > int(height * 0.90):
        return False
    for building in buildings:
        if building.center is None:
            continue
        dx = abs(center[0] - building.center[0])
        dy = abs(center[1] - building.center[1])
        if dx <= max(120, int(width * 0.12)) and dy <= max(75, int(height * 0.10)):
            return True
    return False


def _metadata(content: str, marker_name: str) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool] = {"content": content}
    if marker_name == "building_value":
        match = re.search(r"\d+", content)
        if match:
            metadata["value"] = int(match.group())
    if marker_name in {"vehicle_locked", "vehicle_repair", "busy_popup"}:
        metadata["unavailable"] = True
    return metadata


def _classify(texts: list[str], markers: list[Marker]) -> tuple[ScreenKind, str]:
    names = {marker.name for marker in markers}
    if "battle_start_confirm" in names:
        return ScreenKind.BATTLE_START_CONFIRM, "battle_start_confirmation"
    if "result_confirm_button" in names and ({"victory", "defeat"} & names):
        return ScreenKind.BATTLE_RESULT, "battle_result"
    if "distraction_popup" in names or "busy_popup" in names:
        return ScreenKind.POPUP, "interrupting_popup"
    if "watch_button" in names:
        return ScreenKind.BATTLE_RUNNING, "watch_prompt"
    if "attack_entry" in names:
        return ScreenKind.CITY_WAR_ATTACK_ENTRY, "red_attack_entry"
    attack_buttons = [marker for marker in markers if marker.name == "attack_button"]
    attack_context = {"city_war_title", "city_war_entry", "building", "building_value"}
    if (attack_buttons and any(
        marker.bbox is None or (marker.metadata or {}).get("position") == "bottom_left"
        for marker in attack_buttons
    )) or "defense_button" in names or ("attack_button" in names and names & attack_context):
        return ScreenKind.ATTACK_DEFENSE, "attack_defense_page"
    if "opponent_list" in names or "vehicle_target" in names:
        return ScreenKind.VEHICLE_SELECT, "enemy_vehicle_grid"
    if "building" in names or "building_value" in names:
        return ScreenKind.BUILDING_MAP, "building_map"
    loadout = [marker for marker in markers if marker.name == "loadout_start"]
    if loadout and (any((marker.metadata or {}).get("position") == "bottom_right" for marker in loadout)
                    or names & {"city_war_title", "join_button", "match_wait"}):
        return ScreenKind.LOADOUT_CONFIRM, "loadout_confirmation"
    if ("join_button" in names and ({"city_war_title", "match_wait"} & names)) \
            or "match_wait" in names or "city_war_title" in names:
        return ScreenKind.CITY_WAR, "city_war_page"
    if {"guild_entry", "city_war_promo"} & names:
        return ScreenKind.HOME, "home_guild_entry"
    if any("CATS" in text.upper() for text in texts):
        return ScreenKind.LOADING, "game_loading"
    return ScreenKind.UNKNOWN, "no_page_signature"


def _annotate_colors(image, markers: list[Marker]) -> list[Marker]:
    annotated: list[Marker] = []
    for marker in markers:
        metadata = dict(marker.metadata or {})
        name = marker.name
        if marker.center is not None:
            x, y = marker.center
            if x < image.width * 0.50 and y > image.height * 0.58:
                metadata["position"] = "bottom_left"
            elif x > image.width * 0.55 and y > image.height * 0.55:
                metadata["position"] = "bottom_right"
            elif y < image.height * 0.18:
                metadata["position"] = "top_bar"
            else:
                metadata["position"] = "center"
        if marker.name == "attack_button" and marker.center is not None:
            red, blue = _color_counts(image, marker.center, radius=18)
            metadata["red_pixels"] = red
            metadata["blue_pixels"] = blue
            # The red city-war entry is a distinct action from the lower-left
            # attack control. Keep both names explicit in the state machine.
            if metadata.get("position") != "bottom_left":
                icon = _find_red_attack_icon(image, marker.center)
                if icon is not None:
                    name = "attack_entry"
                    annotated.append(Marker(
                        "attack_entry", marker.confidence, _center(icon), icon,
                        {**metadata, "red_icon": True},
                    ))
                    continue
        if marker.name == "building" and marker.center is not None:
            red, blue = _color_counts(image, marker.center, radius=16)
            if red or blue:
                metadata["side"] = "enemy" if red > blue else "us"
                metadata["red_pixels"] = red
                metadata["blue_pixels"] = blue
        annotated.append(Marker(name, marker.confidence, marker.center, marker.bbox, metadata))
    blue, red = _scan_progress_colors(image)
    if blue:
        annotated.append(Marker("blue_progress", min(1.0, blue / 5000), None, None, {"pixels": blue}))
    if red:
        annotated.append(Marker("red_progress", min(1.0, red / 5000), None, None, {"pixels": red}))
    return annotated


def _find_red_attack_icon(image, anchor: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """Find the red attack emblem above the attack label, not red UI chrome."""
    ax, ay = anchor
    points: list[tuple[int, int]] = []
    for y in range(max(0, ay - 190), max(0, ay - 18), 3):
        for x in range(max(0, ax - 145), min(image.width, ax + 145), 3):
            r, g, b = image.getpixel((x, y))
            if r > 155 and r > g + 45 and r > b + 45:
                points.append((x, y))
    if len(points) < 20:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    if bbox[2] - bbox[0] < 18 or bbox[3] - bbox[1] < 18:
        return None
    return bbox


def _contextualize_markers(
    texts: list[str], markers: list[Marker], width: int, height: int
) -> list[Marker]:
    """Apply page context after OCR; raw words alone are never actions."""
    names = {marker.name for marker in markers}
    contextual: list[Marker] = []
    has_city_context = bool(names & {"city_war_title", "match_wait", "join_button", "opponent_list"})
    joined_text = "".join(_normalize_text(text) for text in texts)
    interruption_phrases = (
        "废料兑换", "吞拿石", "instagram", "礼包", "同捆包", "获取分享编辑",
        "帮派框排名", "领取了所有奖励", "应用内购买不可用",
        "你的帮派发动了攻击", "帮派发动了", "快加入", "新的回合已开始",
    )
    for marker in markers:
        name = marker.name
        metadata = dict(marker.metadata or {})
        x, y = marker.center or (0, 0)
        position = metadata.get("position")
        if name == "city_war_title_candidate":
            name = "city_war_title" if y < height * 0.22 else "city_war_promo"
        elif name == "confirm_button":
            if names & {"victory", "defeat"}:
                name = "result_confirm_button"
            else:
                name = "popup_confirm_button"
        elif name == "join_button":
            if not (position == "bottom_right" and (has_city_context or "city_war_title_candidate" in names)):
                continue
        elif name == "loadout_start":
            if position != "bottom_right":
                continue
        elif name == "attack_button":
            if position != "bottom_left" and not metadata.get("red_icon"):
                continue
        elif name == "vehicle_target":
            if "opponent_list" not in names and "vehicle_target" not in names:
                continue
        elif name == "vehicle_repair" and x < width * 0.50 and y > height * 0.62:
            name = "own_vehicle_repair"
        elif name == "system_overlay" and not (names & {
            "city_war_title_candidate", "city_war_title", "opponent_list", "building",
        }):
            name = "distraction_popup"
        contextual.append(Marker(name, marker.confidence, marker.center, marker.bbox, metadata))
    if any(phrase in joined_text for phrase in interruption_phrases):
        contextual.append(Marker("distraction_popup", 0.90, None, None, {"context": "interruption_text"}))
    elif "gang_war_entry" in names and any(
        marker.name == "popup_confirm_button" for marker in contextual
    ):
        contextual.append(Marker("distraction_popup", 0.88, None, None, {"context": "round_dialog"}))
    return contextual


def _color_counts(image, center: tuple[int, int], radius: int) -> tuple[int, int]:
    red = blue = 0
    x0, y0 = center
    for y in range(max(0, y0 - radius), min(image.height, y0 + radius + 1), 2):
        for x in range(max(0, x0 - radius), min(image.width, x0 + radius + 1), 2):
            r, g, b = image.getpixel((x, y))
            if r > 130 and r > g + 35 and r > b + 35:
                red += 1
            elif b > 110 and b > r + 25 and b > g + 15:
                blue += 1
    return red, blue


def _scan_progress_colors(image) -> tuple[int, int]:
    red = blue = 0
    top = int(image.height * 0.10)
    bottom = int(image.height * 0.45)
    for y in range(top, bottom, 3):
        for x in range(0, image.width, 3):
            r, g, b = image.getpixel((x, y))
            if r > 150 and r > g + 45 and r > b + 35:
                red += 1
            elif b > 120 and b > r + 30 and b > g + 15:
                blue += 1
    return blue, red


def _state_confidence(markers: list[Marker], kind: ScreenKind) -> float:
    if not markers:
        return 0.0
    return min(1.0, max(marker.confidence for marker in markers) * (1.0 if kind != ScreenKind.UNKNOWN else 0.5))
