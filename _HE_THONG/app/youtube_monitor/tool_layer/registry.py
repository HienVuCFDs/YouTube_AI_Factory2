from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ToolCategory = Literal["READ", "PLAN", "EXECUTE", "RENDER"]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    category: ToolCategory
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False
    destructive: bool = False

    def as_mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "openWorldHint": False,
                "category": self.category,
            },
        }


_PROJECT_ID = {"type": "integer", "description": "ID du an YouTube AI Factory"}


ASTRA_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="youtube_factory_get_project_context",
        category="READ",
        read_only=True,
        description=(
            "Lay ProjectContext compact cho Astra: source, workflow, script, storyboard, "
            "timeline, job, readiness va next actions ma khong tai media nang."
        ),
        input_schema={
            "type": "object",
            "properties": {"project_id": _PROJECT_ID},
            "required": ["project_id"],
        },
    ),

    ToolDefinition(
        name="youtube_factory_get_project_edit_plan",
        category="READ",
        read_only=True,
        description="Lay ke hoach dung AI hien tai cua project, gom transition/effect/overlay/sound cue/required assets theo tung canh.",
        input_schema={"type": "object", "properties": {"project_id": _PROJECT_ID}, "required": ["project_id"]},
    ),
    ToolDefinition(
        name="youtube_factory_plan_project_edit",
        category="PLAN",
        description="Yeu cau AI Director lap edit plan v2 cho toan bo timeline; chua ap dung vao canh cho den khi approve/apply.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "motion_policy": {"type": "string", "enum": ["balanced", "gif_only"], "default": "balanced"},
            },
            "required": ["project_id"],
        },
    ),

    ToolDefinition(
        name="youtube_factory_update_project_edit_scene",
        category="PLAN",
        description="Sua mot scene trong edit plan draft: transition/effect/overlay/sound cue/required assets/direction truoc khi approve va apply.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "segment_id": {"type": "integer", "description": "ID timeline segment/canh"},
                "changes": {
                    "type": "object",
                    "description": "Patch theo UpdateScenePlanRequest: overlays, sound_cues, transition, effect, required_assets, direction, note...",
                },
            },
            "required": ["project_id", "segment_id", "changes"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_approve_project_edit_plan",
        category="EXECUTE",
        description="Duyet edit plan hien tai sau khi Astra da review cau truc ke hoach.",
        input_schema={"type": "object", "properties": {"project_id": _PROJECT_ID}, "required": ["project_id"]},
    ),
    ToolDefinition(
        name="youtube_factory_apply_project_edit_plan",
        category="EXECUTE",
        description="Ap dung edit plan da duyet vao timeline scenes: transition, effect, overlays, sound cues, required assets va edit beats.",
        input_schema={"type": "object", "properties": {"project_id": _PROJECT_ID}, "required": ["project_id"]},
    ),
    ToolDefinition(
        name="youtube_factory_get_storyboard_required_jobs",
        category="READ",
        read_only=True,
        description="Liet ke media/SFX/graphic assets can co sau khi ap dung edit plan, khong queue job.",
        input_schema={"type": "object", "properties": {"project_id": _PROJECT_ID}, "required": ["project_id"]},
    ),
    ToolDefinition(
        name="youtube_factory_plan_scene_edit_beats",
        category="PLAN",
        description=(
            "Lap ke hoach dung cho mot scene cu the: visual beats, chu dong overlay va sound cues. "
            "Chua tao asset AI, chi luu plan vao timeline scene."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "segment_id": {"type": "integer", "description": "ID timeline segment/canh"},
                "max_beats": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
            },
            "required": ["project_id", "segment_id"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_apply_scene_edit_beats",
        category="EXECUTE",
        description=(
            "Ap dung ke hoach dung cua mot scene: trich frame neu can, tao SFX preset, "
            "va queue anh AI phu neu beat yeu cau."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "segment_id": {"type": "integer", "description": "ID timeline segment/canh"},
                "image_provider": {"type": "string", "default": "auto"},
                "ratio": {"type": "string", "enum": ["1280:720", "720:1280", "1024:1024"], "default": "1280:720"},
                "confirmed": {"type": "boolean", "description": "Bat buoc true neu co tao anh AI phu"},
            },
            "required": ["project_id", "segment_id"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_get_render_readiness",
        category="READ",
        read_only=True,
        description="Kiem tra cac file that can co de render, khong phu thuoc edit plan blocker.",
        input_schema={"type": "object", "properties": {"project_id": _PROJECT_ID}, "required": ["project_id"]},
    ),
    ToolDefinition(
        name="youtube_factory_search_web",
        category="READ",
        read_only=True,
        description=(
            "Tra cuu web: tra ve tieu de, trich doan va link de dinh huong. "
            "Khong phai noi dung da kiem chung — doc roi tu viet lai bang loi cua minh."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Cau can tra cuu"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_get_scene_speech_timing",
        category="READ",
        read_only=True,
        description=(
            "Moc thoi gian tung chu trong loi doc cua mot canh, kem cac cho ngat hoi. "
            "Dung de dat cat dung trong am hoac giu hinh qua doan nghi, thay vi cat theo cam tinh."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "segment_id": {"type": "integer", "description": "ID timeline segment/canh"},
            },
            "required": ["project_id", "segment_id"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_get_contact_sheet",
        category="READ",
        read_only=True,
        description=(
            "Tao MOT anh tong hop de NHIN thay project dang the nao: cac khung hinh lay deu tren video "
            "da render, hoac cac canh hien co neu chua render. Tra ve duong dan file de mo ra xem. "
            "Dung truoc khi duyet ket qua thay vi duyet mu."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "tiles": {"type": "integer", "minimum": 1, "maximum": 24, "default": 12},
            },
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_list_steps",
        category="READ",
        read_only=True,
        description=(
            "Trang thai tung buoc lam video cua project: da xong / san sang / con thieu buoc nao, "
            "buoc nao tieu luot tra phi. Day la danh sach buoc ma nut bam tren giao dien cung dung. "
            "Goi tool nay TRUOC khi lam va SAU khi lam de kiem tra that; dung no thay cho viec nhin giao dien."
        ),
        input_schema={
            "type": "object",
            "properties": {"project_id": _PROJECT_ID},
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_run_step",
        category="EXECUTE",
        description=(
            "Chay mot buoc lam video (analyze, script, shots, timeline, voice, edit_plan, render...). "
            "Cung mot duong ma nut bam tren giao dien goi, nen ket qua giong het - dung tool nay thay vi bam nut. "
            "Buoc chua du dieu kien se bi tu choi kem ly do: doc ly do, chay buoc con thieu roi goi lai."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "step": {"type": "string", "description": "Khoa cua buoc, lay tu youtube_factory_list_steps"},
                "options": {
                    "type": "object",
                    "description": (
                        "Tuy chon cua buoc. provider: AI/engine se lam (vd codex_cli, claude_code_cli, antigravity; "
                        "xem youtube_factory_get_ai_runtimes). analyze voi nguon san pham: browser_session=profile:<nen tang> "
                        "hoac extension:browser (xem youtube_factory_list_connections). "
                        "script: draft={script_title,hook,intro,main_content,cta} "
                        "de luu kich ban tu viet. shots: shots=[...] de luu danh sach canh tu viet. force: lam lai. "
                        "confirmed: dong y tieu luot."
                    ),
                },
            },
            "required": ["project_id", "step"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_get_ai_runtimes",
        category="READ",
        read_only=True,
        description=(
            "Kiem tra runtime AI nao that su chay duoc ngay bay gio (login/API key/MCP tunnel), "
            "kem ly do neu chua san sang va thu tu uu tien cho buoc viet kich ban."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="youtube_factory_get_orchestrator_report",
        category="READ",
        read_only=True,
        description=(
            "Lay nhat ky audit tung buoc AI cua project: model/tool da chon, ly do, ket qua, "
            "trang thai va co dung fallback hay khong."
        ),
        input_schema={
            "type": "object",
            "properties": {"project_id": _PROJECT_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}},
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_list_connections",
        category="READ",
        read_only=True,
        description=(
            "Nang luc doc trang san pham cua app: moi nen tang (Shopee, TikTok Shop, Lazada, Tiki, Sendo) dang "
            "CONNECTED / DISCONNECTED / NEED_LOGIN / EXPIRED / ERROR, qua duong nao (vd 'shopee: CONNECTED via extension:coccoc'), "
            "co doc duoc khong (can_read), va cac Browser Bridge (extension trong trinh duyet that cua nguoi dung). Dung khi analyze bao trang san pham chua doc duoc "
            "de chon cach doc khac. Khong tra cookie, mat khau hay duong dan profile; dang nhap la viec cua nguoi dung."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="youtube_factory_get_connection_status",
        category="READ",
        read_only=True,
        description="Trang thai ket noi cua mot nen tang (shopee, tiktok, lazada, tiki, sendo).",
        input_schema={
            "type": "object",
            "properties": {"platform": {"type": "string", "description": "shopee | tiktok | lazada | tiki | sendo"}},
            "required": ["platform"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_read_product",
        category="READ",
        read_only=True,
        description=(
            "ProductReader: doc MOT trang san pham qua ket noi cua app (profile rieng cua nen tang, roi Browser "
            "Bridge). session_id tuy chon: profile:<nen tang> hoac extension:browser. Tra status OK / NEED_LOGIN / "
            "NEED_HUMAN_VERIFY / UNAVAILABLE / FAILED, ten, gia, anh va mot doan noi dung trang. Khong luu vao du an: "
            "muon luu thi chay analyze voi options.browser_session. Khong giai captcha, khong dang nhap ho."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Link san pham"},
                "session_id": {"type": "string", "description": "profile:<nen tang> | extension:<trinh duyet, vd coccoc> | extension:browser (bat ky); bo trong de app tu chon"},
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        name="youtube_factory_get_source_package",
        category="READ",
        read_only=True,
        description=(
            "Lay SourcePackage compact cua project: loai nguon, metadata, transcript preview, "
            "analyses va asset counts de Astra quyet dinh chien luoc."
        ),
        input_schema={
            "type": "object",
            "properties": {"project_id": _PROJECT_ID},
            "required": ["project_id"],
        },
    ),
)


def astra_mcp_tool_definitions() -> list[dict[str, Any]]:
    return [tool.as_mcp_tool() for tool in ASTRA_TOOL_DEFINITIONS]


def astra_tool_names() -> set[str]:
    return {tool.name for tool in ASTRA_TOOL_DEFINITIONS}
