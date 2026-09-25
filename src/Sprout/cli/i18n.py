"""Small shared language switch for CLI output."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

_SETTINGS_FILE = Path.home() / ".sprout" / "settings.json"
_LANGUAGES = ("zh", "en", "ja", "ko", "ru", "es", "pt", "zh-Hant")
_LANGUAGE_INTENT_THRESHOLD = 0.56
_LANGUAGE_INTENT_EMBEDDER = None
_LANGUAGE_INTENT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_ALIASES = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh_cn": "zh",
    "mandarin": "zh",
    "simplified chinese": "zh",
    "chinese": "zh",
    "简体": "zh",
    "简体中文": "zh",
    "简體中文": "zh",
    "中文": "zh",
    "汉语": "zh",
    "漢語": "zh",
    "普通话": "zh",
    "普通話": "zh",
    "中国語": "zh",
    "중국어": "zh",
    "китайский": "zh",
    "chino": "zh",
    "chinês": "zh",
    "en": "en",
    "eng": "en",
    "english": "en",
    "英语": "en",
    "英文": "en",
    "英語": "en",
    "inglés": "en",
    "ingles": "en",
    "inglês": "en",
    "английский": "en",
    "영어": "en",
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "日语": "ja",
    "日文": "ja",
    "日語": "ja",
    "日本語": "ja",
    "일본어": "ja",
    "японский": "ja",
    "japonés": "ja",
    "japones": "ja",
    "japonês": "ja",
    "ko": "ko",
    "kr": "ko",
    "kor": "ko",
    "korean": "ko",
    "韩语": "ko",
    "韓語": "ko",
    "韩文": "ko",
    "韓文": "ko",
    "한국어": "ko",
    "корейский": "ko",
    "coreano": "ko",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "俄语": "ru",
    "俄語": "ru",
    "俄文": "ru",
    "русский": "ru",
    "러시아어": "ru",
    "ruso": "ru",
    "russo": "ru",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "西班牙语": "es",
    "西班牙語": "es",
    "西班牙文": "es",
    "español": "es",
    "espanol": "es",
    "스페인어": "es",
    "испанский": "es",
    "espanhol": "es",
    "pt": "pt",
    "pt-br": "pt",
    "por": "pt",
    "portuguese": "pt",
    "葡萄牙语": "pt",
    "葡萄牙語": "pt",
    "葡萄牙文": "pt",
    "português": "pt",
    "portugues": "pt",
    "포르투갈어": "pt",
    "португальский": "pt",
    "portugués": "pt",
    "portuguesa": "pt",
    "zh-hant": "zh-Hant",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "traditional": "zh-Hant",
    "traditional chinese": "zh-Hant",
    "繁体中文": "zh-Hant",
    "繁體中文": "zh-Hant",
    "繁体": "zh-Hant",
    "繁體": "zh-Hant",
    "正體中文": "zh-Hant",
}
_LANGUAGE_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "ru": "Русский",
    "es": "Español",
    "pt": "Português",
    "zh-Hant": "繁體中文",
}
_IDENTITY_PHRASES = {
    "zh": ("你是谁", "你叫什么", "介绍自己", "你能做什么", "你会什么", "功能"),
    "en": ("who are you", "what can you do", "what do you do", "capabilities"),
    "ja": ("あなたは誰", "何ができますか", "何ができる", "自己紹介"),
    "ko": ("누구야", "당신은 누구", "무엇을 할 수", "자기소개"),
    "ru": ("кто ты", "что ты умеешь", "представься"),
    "es": ("quién eres", "qué puedes hacer", "preséntate"),
    "pt": ("quem é você", "o que você pode fazer", "apresente-se"),
    "zh-Hant": ("你是誰", "你能做什麼", "自我介紹"),
}
_LANGUAGE_REQUEST_MARKERS = (
    "切换语言",
    "切换到",
    "切换为",
    "切換語言",
    "切換到",
    "切換為",
    "换回",
    "换成",
    "换为",
    "換回",
    "換成",
    "換為",
    "改成",
    "改为",
    "改回",
    "改為",
    "设置语言",
    "設定語言",
    "使用",
    "请用",
    "請用",
    "switch language",
    "change language",
    "switch to",
    "change to",
    "use ",
    "set language",
    "set ui language",
    "切り替え",
    "切り替えて",
    "変えて",
    "変更",
    "使って",
    "사용",
    "바꿔",
    "변경",
    "전환",
    "переключ",
    "смени",
    "сменить",
    "используй",
    "cambiar",
    "cambia",
    "cámbialo",
    "usar",
    "usa ",
    "mudar",
    "mude",
    "trocar",
    "troque",
    "usar ",
)
_SEMANTIC_LANGUAGE_REQUESTS = {
    "zh": (
        "换回中文",
        "切换成简体中文",
        "以后用中文回答",
        "用我刚才那种中文回答",
        "please respond in Chinese from now on",
    ),
    "en": (
        "use English",
        "switch to English",
        "please answer in English",
        "respond in English from now on",
    ),
    "ja": (
        "换为日语",
        "switch to Japanese",
        "日本語に切り替えて",
        "日本語で答えて",
        "能不能讲日本那边的话",
        "please respond in Japanese from now on",
    ),
    "ko": (
        "switch to Korean",
        "한국어로 바꿔줘",
        "한국어로 답해줘",
        "please respond in Korean from now on",
    ),
    "ru": (
        "switch to Russian",
        "переключи на русский",
        "отвечай по-русски",
        "please respond in Russian from now on",
    ),
    "es": (
        "switch to Spanish",
        "cambiar a español",
        "responde en español",
        "please respond in Spanish from now on",
    ),
    "pt": (
        "switch to Portuguese",
        "mudar para português",
        "responda em português",
        "please respond in Portuguese from now on",
    ),
    "zh-Hant": (
        "換回繁體中文",
        "切換成繁體中文",
        "請用繁體中文回答",
        "please respond in Traditional Chinese from now on",
    ),
}
_TRANSLATIONS: dict[tuple[str, str], dict[str, str]] = {}
_SEMANTIC_LANGUAGE_VECTORS: tuple[tuple[str, str, list[float]], ...] | None = None


def current_language() -> str:
    """Return the active CLI language code."""
    configured = os.getenv("SPROUT_CLI_LANG")
    if configured:
        return _normalize(configured)
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        configured = data.get("language") or data.get("locale")
        return _normalize(configured) if configured else "zh"
    except (OSError, ValueError):
        return "zh"


def L(zh: str, en: str) -> str:
    """Return the active language string."""
    language = current_language()
    translated = _TRANSLATIONS.get((zh, en), {}).get(language)
    if translated:
        return translated
    if language == "zh":
        return zh
    if language == "zh-Hant":
        translated = _TRANSLATIONS.get((zh, en), {}).get("zh-Hant")
        if translated:
            return translated
        return zh
    return en


def supported_languages() -> tuple[str, ...]:
    return _LANGUAGES


def language_request(text: str) -> str | None:
    """Extract a requested CLI language from natural language, if explicit."""
    folded = text.casefold().strip()
    if not folded:
        return None
    has_switch_marker = any(marker in folded for marker in _LANGUAGE_REQUEST_MARKERS)
    has_language_phrase = bool(
        re.search(
            r"(?:切换|切換|换|換|改|设置|設定|使用|请用|請用).{0,8}"
            r"(?:语言|語言|界面语言|介面語言)",
            folded,
        )
    )
    if has_switch_marker or has_language_phrase:
        explicit = _language_from_alias(folded)
        if explicit:
            return explicit
    semantic = _semantic_language_request(folded)
    if semantic is not None:
        return semantic
    return None


def language_command(text: str) -> tuple[str, str] | None:
    """Return the equivalent slash command and its canonical language code."""
    language = language_request(text)
    return ("/language", language) if language is not None else None


def language_name(language: str) -> str:
    return _LANGUAGE_NAMES.get(_normalize(language), _normalize(language))


def _contains_language_alias(text: str, alias: str) -> bool:
    if alias.isascii():
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text))
    return alias in text


def _language_from_alias(text: str) -> str | None:
    aliases = sorted(_ALIASES, key=len, reverse=True)
    for alias in aliases:
        if _contains_language_alias(text, alias):
            return _ALIASES[alias]
    return None


def _semantic_language_request(text: str) -> str | None:
    vector = _language_intent_embed(text)
    best_language = None
    best_score = 0.0
    for language, _phrase, phrase_vector in _semantic_language_vectors():
        score = _cosine(vector, phrase_vector)
        if score > best_score:
            best_language = language
            best_score = score
    if best_score >= _LANGUAGE_INTENT_THRESHOLD:
        return best_language
    return None


def _semantic_language_vectors() -> tuple[tuple[str, str, list[float]], ...]:
    global _SEMANTIC_LANGUAGE_VECTORS
    if _SEMANTIC_LANGUAGE_VECTORS is None:
        _SEMANTIC_LANGUAGE_VECTORS = tuple(
            (language, phrase, _language_intent_embed(phrase))
            for language, phrases in _SEMANTIC_LANGUAGE_REQUESTS.items()
            for phrase in phrases
        )
    return _SEMANTIC_LANGUAGE_VECTORS


def _language_intent_embed(text: str) -> list[float]:
    global _LANGUAGE_INTENT_EMBEDDER
    if _LANGUAGE_INTENT_EMBEDDER is None:
        _LANGUAGE_INTENT_EMBEDDER = _CliIntentEmbedder(dim=256)
    return _LANGUAGE_INTENT_EMBEDDER(text)


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class _CliIntentEmbedder:
    """Local semantic embedder for CLI intent matching.

    Prefer a small open-source multilingual sentence-transformer when it is
    installed. The hashing fallback keeps the CLI usable in offline/minimal
    installs and gives tests a deterministic path.
    """

    def __init__(self, dim: int) -> None:
        self._backend = _SentenceTransformerIntentEmbedder.load()
        if self._backend is None:
            self._backend = _HashIntentEmbedder(dim=dim)

    def __call__(self, text: str) -> list[float]:
        return self._backend(text)


class _SentenceTransformerIntentEmbedder:
    def __init__(self, model: object) -> None:
        self._model = model

    @classmethod
    def load(cls) -> _SentenceTransformerIntentEmbedder | None:
        backend = os.getenv("SPROUT_CLI_INTENT_EMBEDDING_BACKEND", "auto").casefold()
        if backend in {"hash", "off", "false", "0"}:
            return None
        model_name = os.getenv("SPROUT_CLI_INTENT_EMBEDDING_MODEL", _LANGUAGE_INTENT_MODEL)
        try:
            from sentence_transformers import SentenceTransformer

            return cls(SentenceTransformer(model_name))
        except Exception:
            return None

    def __call__(self, text: str) -> list[float]:
        try:
            vector = self._model.encode(
                text,
                convert_to_numpy=False,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except TypeError:
            vector = self._model.encode(text)
        return _normalize_vector([float(value) for value in vector])


class _HashIntentEmbedder:
    """Tiny deterministic fallback embedder for local CLI intent matching."""

    _TOKEN_RE = re.compile(r"[\w]+|[\u4e00-\u9fff]")

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def __call__(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = self._TOKEN_RE.findall(text.casefold())
        for token in tokens:
            self._add_token(vector, token, salt=0)
            padded = f"  {token} "
            for index in range(len(padded) - 2):
                self._add_token(vector, padded[index : index + 3], salt=1)
        norm = math.sqrt(sum(component * component for component in vector))
        return _normalize_vector(vector) if norm > 0.0 else vector

    def _add_token(self, vector: list[float], token: str, *, salt: int) -> None:
        digest = hashlib.md5(f"{salt}:{token}".encode()).digest()
        value = int.from_bytes(digest[:4], "big")
        sign = -1.0 if digest[4] & 1 else 1.0
        vector[value % self.dim] += sign


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return vector
    return [component / norm for component in vector]


def identity_question_phrases() -> tuple[str, ...]:
    return tuple(phrase for phrases in _IDENTITY_PHRASES.values() for phrase in phrases)


def add_translations(zh: str, en: str, values: dict[str, str]) -> None:
    _TRANSLATIONS[(zh, en)] = values


def set_language(language: str) -> None:
    """Update the active language and persist it for future CLI sessions."""
    normalized = _normalize(language)
    os.environ["SPROUT_CLI_LANG"] = normalized
    data: dict[str, object] = {}
    if _SETTINGS_FILE.is_file():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data["language"] = normalized
    data["locale"] = {
        "zh": "zh-CN",
        "en": "en-US",
        "ja": "ja-JP",
        "ko": "ko-KR",
        "ru": "ru-RU",
        "es": "es-ES",
        "pt": "pt-BR",
        "zh-Hant": "zh-TW",
    }[normalized]
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize(language: str) -> str:
    value = language.strip().lower()
    if value in _ALIASES:
        return _ALIASES[value]
    if value.startswith("zh"):
        return "zh"
    if value.startswith("ja") or value.startswith("jp"):
        return "ja"
    if value.startswith("ko") or value.startswith("kr"):
        return "ko"
    if value.startswith("ru"):
        return "ru"
    if value.startswith("es"):
        return "es"
    if value.startswith("pt"):
        return "pt"
    return "en"


def _register_default_translations() -> None:
    add_translations(
        "[1/3] 初始化 ~/.sprout 目录布局",
        "[1/3] Ensuring ~/.sprout directory layout...",
        {
            "ja": "[1/3] ~/.sprout ディレクトリを初期化中...",
            "ko": "[1/3] ~/.sprout 디렉터리 초기화 중...",
            "ru": "[1/3] Инициализация каталога ~/.sprout...",
            "es": "[1/3] Inicializando el directorio ~/.sprout...",
            "pt": "[1/3] Inicializando o diretório ~/.sprout...",
            "zh-Hant": "[1/3] 初始化 ~/.sprout 目錄佈局...",
        },
    )
    add_translations(
        "[2/3] 写入缺失的配置文件",
        "[2/3] Writing missing config files...",
        {
            "ja": "[2/3] 不足している設定ファイルを書き込み中...",
            "ko": "[2/3] 누락된 설정 파일 쓰는 중...",
            "ru": "[2/3] Запись отсутствующих файлов конфигурации...",
            "es": "[2/3] Escribiendo archivos de configuración faltantes...",
            "pt": "[2/3] Gravando arquivos de configuração ausentes...",
            "zh-Hant": "[2/3] 寫入缺失的設定檔...",
        },
    )
    add_translations(
        "[3/3] 预留本地数据库",
        "[3/3] Reserving local databases...",
        {
            "ja": "[3/3] ローカルデータベースを予約中...",
            "ko": "[3/3] 로컬 데이터베이스 예약 중...",
            "ru": "[3/3] Резервирование локальных баз данных...",
            "es": "[3/3] Reservando bases de datos locales...",
            "pt": "[3/3] Reservando bancos de dados locais...",
            "zh-Hant": "[3/3] 預留本機資料庫...",
        },
    )
    add_translations(
        "Sprout 主目录已就绪",
        "Sprout home ready.",
        {
            "ja": "Sprout ホームの準備ができました。",
            "ko": "Sprout 홈이 준비되었습니다.",
            "ru": "Каталог Sprout готов.",
            "es": "Directorio de Sprout listo.",
            "pt": "Diretório do Sprout pronto.",
            "zh-Hant": "Sprout 主目錄已就緒。",
        },
    )
    add_translations(
        "[temporal] 必需（默认地址 127.0.0.1:7233）",
        "[temporal] required (default 127.0.0.1:7233)",
        {
            "ja": "[temporal] 必須（既定値 127.0.0.1:7233）",
            "ko": "[temporal] 필수 (기본값 127.0.0.1:7233)",
            "ru": "[temporal] требуется (по умолчанию 127.0.0.1:7233)",
            "es": "[temporal] requerido (predeterminado 127.0.0.1:7233)",
            "pt": "[temporal] obrigatório (padrão 127.0.0.1:7233)",
            "zh-Hant": "[temporal] 必需（預設位址 127.0.0.1:7233）",
        },
    )
    add_translations(
        "[temporal] 已启用",
        "[temporal] enabled",
        {
            "ja": "[temporal] 有効",
            "ko": "[temporal] 활성화됨",
            "ru": "[temporal] включено",
            "es": "[temporal] habilitado",
            "pt": "[temporal] habilitado",
            "zh-Hant": "[temporal] 已啟用",
        },
    )
    add_translations(
        "自我进化的软件项目基因引擎",
        "A self-evolving gene for software projects",
        {
            "ja": "ソフトウェアプロジェクトの自己進化ジーン",
            "ko": "소프트웨어 프로젝트를 위한 자기 진화 유전자",
            "ru": "Саморазвивающийся ген для программных проектов",
            "es": "Un gen autoevolutivo para proyectos de software",
            "pt": "Um gene autoevolutivo para projetos de software",
            "zh-Hant": "自我進化的軟體專案基因引擎",
        },
    )
    add_translations(
        "交互式对话",
        "Interactive chat",
        {
            "ja": "対話モード",
            "ko": "대화형 채팅",
            "ru": "Интерактивный чат",
            "es": "Chat interactivo",
            "pt": "Chat interativo",
            "zh-Hant": "互動式對話",
        },
    )
    add_translations(
        "对话已结束",
        "Chat ended.",
        {
            "ja": "チャットを終了しました。",
            "ko": "채팅이 종료되었습니다.",
            "ru": "Чат завершён.",
            "es": "Chat finalizado.",
            "pt": "Chat encerrado.",
            "zh-Hant": "對話已結束。",
        },
    )
    add_translations(
        "当前会话已停止，开始新会话",
        "Session stopped. Starting a new session.",
        {
            "ja": "セッションを停止しました。新しいセッションを開始します。",
            "ko": "세션을 중지했습니다. 새 세션을 시작합니다.",
            "ru": "Сессия остановлена. Начинаем новую сессию.",
            "es": "Sesión detenida. Iniciando una nueva sesión.",
            "pt": "Sessão interrompida. Iniciando uma nova sessão.",
            "zh-Hant": "目前工作階段已停止，開始新的工作階段。",
        },
    )


_register_default_translations()


def _register_menu_translations() -> None:
    add_translations(
        "显示所有可用命令",
        "Show all available commands",
        {
            "ja": "利用可能なコマンドを表示",
            "ko": "사용 가능한 명령 표시",
            "ru": "Показать все доступные команды",
            "es": "Mostrar todos los comandos disponibles",
            "pt": "Mostrar todos os comandos disponíveis",
            "zh-Hant": "顯示所有可用命令",
        },
    )
    add_translations(
        "显示命令列表及详细说明",
        "Show command list and details",
        {
            "ja": "コマンド一覧と詳細を表示",
            "ko": "명령 목록 및 세부 정보 표시",
            "ru": "Показать список команд и детали",
            "es": "Mostrar lista de comandos y detalles",
            "pt": "Mostrar lista de comandos e detalhes",
            "zh-Hant": "顯示命令列表及詳細說明",
        },
    )
    add_translations(
        "切换界面语言",
        "Switch UI language",
        {
            "ja": "表示言語を切り替える",
            "ko": "인터페이스 언어 전환",
            "ru": "Сменить язык интерфейса",
            "es": "Cambiar idioma de la interfaz",
            "pt": "Alterar idioma da interface",
            "zh-Hant": "切換介面語言",
        },
    )
    add_translations(
        "清空当前终端屏幕",
        "Clear current terminal screen",
        {
            "ja": "現在のターミナル画面をクリア",
            "ko": "현재 터미널 화면 지우기",
            "ru": "Очистить текущий экран терминала",
            "es": "Limpiar la pantalla del terminal",
            "pt": "Limpar a tela do terminal",
            "zh-Hant": "清空目前終端機畫面",
        },
    )
    add_translations(
        "返回普通对话模式，继续输入消息",
        "Return to normal chat mode",
        {
            "ja": "通常のチャットモードに戻る",
            "ko": "일반 채팅 모드로 돌아가기",
            "ru": "Вернуться в обычный режим чата",
            "es": "Volver al modo de chat normal",
            "pt": "Voltar ao modo de chat normal",
            "zh-Hant": "返回一般對話模式，繼續輸入訊息",
        },
    )
    add_translations(
        "查看本地数据库连接和状态",
        "Inspect local database health and status",
        {
            "ja": "ローカルデータベースの状態を確認",
            "ko": "로컬 데이터베이스 상태 확인",
            "ru": "Проверить состояние локальных баз данных",
            "es": "Inspeccionar estado de bases de datos locales",
            "pt": "Inspecionar estado dos bancos de dados locais",
            "zh-Hant": "查看本機資料庫連線與狀態",
        },
    )
    add_translations(
        "搜索、查看、压缩或删除会话",
        "Search, view, compact, or delete sessions",
        {
            "ja": "セッションを検索・表示・圧縮・削除",
            "ko": "세션 검색, 보기, 압축 또는 삭제",
            "ru": "Поиск, просмотр, сжатие или удаление сессий",
            "es": "Buscar, ver, compactar o eliminar sesiones",
            "pt": "Pesquisar, ver, compactar ou excluir sessões",
            "zh-Hant": "搜尋、查看、壓縮或刪除工作階段",
        },
    )
    add_translations(
        "技能管理",
        "Skill management",
        {
            "ja": "スキル管理",
            "ko": "스킬 관리",
            "ru": "Управление навыками",
            "es": "Gestión de habilidades",
            "pt": "Gerenciamento de habilidades",
            "zh-Hant": "技能管理",
        },
    )
    add_translations(
        "列出技能注册表",
        "List the skill registry",
        {
            "ja": "スキルレジストリを一覧表示",
            "ko": "스킬 레지스트리 목록",
            "ru": "Показать реестр навыков",
            "es": "Listar el registro de habilidades",
            "pt": "Listar o registro de habilidades",
            "zh-Hant": "列出技能登錄表",
        },
    )
    add_translations(
        "搜索技能源（只读，不下载）",
        "Search a source (read-only)",
        {
            "ja": "スキルソースを検索（読み取り専用）",
            "ko": "스킬 소스 검색(읽기 전용)",
            "ru": "Поиск по источникам навыков (только чтение)",
            "es": "Buscar en una fuente (solo lectura)",
            "pt": "Pesquisar em uma fonte (somente leitura)",
            "zh-Hant": "搜尋技能來源（唯讀，不下載）",
        },
    )
    add_translations(
        "安装技能（走策略引擎与审批）",
        "Install a skill (policy + approval)",
        {
            "ja": "スキルをインストール（ポリシーと承認）",
            "ko": "스킬 설치(정책 및 승인)",
            "ru": "Установить навык (политика и одобрение)",
            "es": "Instalar una habilidad (política y aprobación)",
            "pt": "Instalar uma habilidade (política e aprovação)",
            "zh-Hant": "安裝技能（走策略引擎與審批）",
        },
    )
    add_translations(
        "参数无法解析，请检查引号是否成对",
        "Could not parse arguments; check for unbalanced quotes",
        {
            "ja": "引数を解析できません。引用符を確認してください",
            "ko": "인수를 해석할 수 없습니다. 따옴표를 확인하세요",
            "ru": "Не удалось разобрать аргументы; проверьте кавычки",
            "es": "No se pudieron analizar los argumentos; revise las comillas",
            "pt": "Não foi possível analisar os argumentos; verifique as aspas",
            "zh-Hant": "參數無法解析，請檢查引號是否成對",
        },
    )
    add_translations(
        "用法",
        "Usage",
        {
            "ja": "使い方",
            "ko": "사용법",
            "ru": "Использование",
            "es": "Uso",
            "pt": "Uso",
            "zh-Hant": "用法",
        },
    )
    add_translations(
        "未知子命令",
        "Unknown sub-command",
        {
            "ja": "不明なサブコマンド",
            "ko": "알 수 없는 하위 명령",
            "ru": "Неизвестная подкоманда",
            "es": "Subcomando desconocido",
            "pt": "Subcomando desconhecido",
            "zh-Hant": "未知子命令",
        },
    )
    add_translations(
        "提示：加 --help 查看完整参数",
        "Tip: add --help for the full argument list",
        {
            "ja": "ヒント：--help で引数の一覧を表示",
            "ko": "팁: --help 로 전체 인수 확인",
            "ru": "Подсказка: добавьте --help для списка аргументов",
            "es": "Consejo: añada --help para ver todos los argumentos",
            "pt": "Dica: adicione --help para ver todos os argumentos",
            "zh-Hant": "提示：加 --help 查看完整參數",
        },
    )
    add_translations(
        "停止当前会话",
        "Stop current session",
        {
            "ja": "現在のセッションを停止",
            "ko": "현재 세션 중지",
            "ru": "Остановить текущую сессию",
            "es": "Detener sesión actual",
            "pt": "Parar sessão atual",
            "zh-Hant": "停止目前工作階段",
        },
    )
    add_translations(
        "统一数据库操作",
        "Unified database operations",
        {
            "ja": "統合データベース操作",
            "ko": "통합 데이터베이스 작업",
            "ru": "Унифицированные операции с базами данных",
            "es": "Operaciones de base de datos unificadas",
            "pt": "Operações unificadas de banco de dados",
            "zh-Hant": "統一資料庫操作",
        },
    )
    add_translations(
        "运行时与配置",
        "Runtime and config",
        {
            "ja": "ランタイムと設定",
            "ko": "런타임 및 설정",
            "ru": "Среда выполнения и конфигурация",
            "es": "Tiempo de ejecución y configuración",
            "pt": "Runtime e configuração",
            "zh-Hant": "執行環境與設定",
        },
    )
    add_translations(
        "MCP 服务",
        "MCP server",
        {
            "ja": "MCP サーバー",
            "ko": "MCP 서버",
            "ru": "MCP-сервер",
            "es": "Servidor MCP",
            "pt": "Servidor MCP",
            "zh-Hant": "MCP 服務",
        },
    )
    add_translations(
        "记忆管理",
        "Memory management",
        {
            "ja": "メモリ管理",
            "ko": "메모리 관리",
            "ru": "Управление памятью",
            "es": "Gestión de memoria",
            "pt": "Gerenciamento de memória",
            "zh-Hant": "記憶管理",
        },
    )
    add_translations(
        "项目操作",
        "Project operations",
        {
            "ja": "プロジェクト操作",
            "ko": "프로젝트 작업",
            "ru": "Операции с проектами",
            "es": "Operaciones de proyecto",
            "pt": "Operações de projeto",
            "zh-Hant": "專案操作",
        },
    )
    add_translations(
        "远程操作",
        "Remote operations",
        {
            "ja": "リモート操作",
            "ko": "원격 작업",
            "ru": "Удалённые операции",
            "es": "Operaciones remotas",
            "pt": "Operações remotas",
            "zh-Hant": "遠端操作",
        },
    )
    add_translations(
        "成长平面",
        "Evolution",
        {
            "ja": "成長プレーン",
            "ko": "성장 평면",
            "ru": "Плоскость роста",
            "es": "Plano de evolución",
            "pt": "Plano de crescimento",
            "zh-Hant": "成長平面",
        },
    )
    add_translations(
        "审批操作",
        "Approvals",
        {
            "ja": "承認操作",
            "ko": "승인 작업",
            "ru": "Согласования",
            "es": "Aprobaciones",
            "pt": "Aprovações",
            "zh-Hant": "審批操作",
        },
    )
    add_translations(
        "审计验证",
        "Audit verification",
        {
            "ja": "監査検証",
            "ko": "감사 검증",
            "ru": "Проверка аудита",
            "es": "Verificación de auditoría",
            "pt": "Verificação de auditoria",
            "zh-Hant": "稽核驗證",
        },
    )
    add_translations(
        "启动 Web 控制台",
        "Start web console",
        {
            "ja": "Web コンソールを起動",
            "ko": "웹 콘솔 시작",
            "ru": "Запустить веб-консоль",
            "es": "Iniciar consola web",
            "pt": "Iniciar console web",
            "zh-Hant": "啟動 Web 控制台",
        },
    )
    add_translations(
        "Temporal 任务 worker",
        "Temporal worker",
        {
            "ja": "Temporal タスクワーカー",
            "ko": "Temporal 작업 워커",
            "ru": "Рабочий процесс Temporal",
            "es": "Trabajador de Temporal",
            "pt": "Worker do Temporal",
            "zh-Hant": "Temporal 任務 worker",
        },
    )
    add_translations(
        "切换模型",
        "Switch model",
        {
            "ja": "モデルを切り替える",
            "ko": "모델 전환",
            "ru": "Сменить модель",
            "es": "Cambiar modelo",
            "pt": "Alterar modelo",
            "zh-Hant": "切換模型",
        },
    )
    add_translations(
        "配置外部消息网关",
        "Configure external messaging gateway",
        {
            "ja": "外部メッセージングゲートウェイを設定",
            "ko": "외부 메시징 게이트웨이 구성",
            "ru": "Настроить внешний мессенджер-шлюз",
            "es": "Configurar pasarela de mensajería externa",
            "pt": "Configurar gateway de mensagens externo",
            "zh-Hant": "設定外部訊息閘道",
        },
    )
    add_translations(
        "结束当前 CLI 对话",
        "Exit the current CLI chat",
        {
            "ja": "現在の CLI チャットを終了",
            "ko": "현재 CLI 채팅 종료",
            "ru": "Выйти из текущего CLI-чата",
            "es": "Salir del chat CLI actual",
            "pt": "Sair do chat CLI atual",
            "zh-Hant": "結束目前的 CLI 對話",
        },
    )
    add_translations(
        "配置飞书",
        "Configure Feishu",
        {
            "ja": "Feishu を設定",
            "ko": "Feishu 구성",
            "ru": "Настроить Feishu",
            "es": "Configurar Feishu",
            "pt": "Configurar Feishu",
            "zh-Hant": "設定飛書",
        },
    )
    add_translations(
        "配置微信 iLink",
        "Configure WeChat iLink",
        {
            "ja": "WeChat iLink を設定",
            "ko": "WeChat iLink 구성",
            "ru": "Настроить WeChat iLink",
            "es": "Configurar WeChat iLink",
            "pt": "Configurar WeChat iLink",
            "zh-Hant": "設定微信 iLink",
        },
    )
    add_translations(
        "返回一级",
        "Return to main menu",
        {
            "ja": "メインメニューに戻る",
            "ko": "메인 메뉴로 돌아가기",
            "ru": "Вернуться в главное меню",
            "es": "Volver al menú principal",
            "pt": "Voltar ao menu principal",
            "zh-Hant": "返回主選單",
        },
    )
    add_translations(
        "网关配置",
        "Gateway setup",
        {
            "ja": "ゲートウェイ設定",
            "ko": "게이트웨이 설정",
            "ru": "Настройка шлюза",
            "es": "Configuración de pasarela",
            "pt": "Configuração do gateway",
            "zh-Hant": "閘道設定",
        },
    )
    add_translations(
        "飞书网关",
        "Feishu Gateway",
        {
            "ja": "Feishu ゲートウェイ",
            "ko": "Feishu 게이트웨이",
            "ru": "Шлюз Feishu",
            "es": "Pasarela de Feishu",
            "pt": "Gateway do Feishu",
            "zh-Hant": "飛書閘道",
        },
    )
    add_translations(
        "查看已有配置",
        "View existing",
        {
            "ja": "既存の設定を表示",
            "ko": "기존 설정 보기",
            "ru": "Показать существующую настройку",
            "es": "Ver configuración existente",
            "pt": "Ver configuração existente",
            "zh-Hant": "查看既有設定",
        },
    )
    add_translations(
        "重新配置并覆盖",
        "Reconfigure and overwrite",
        {
            "ja": "再設定して上書き",
            "ko": "재구성 및 덮어쓰기",
            "ru": "Перенастроить и перезаписать",
            "es": "Reconfigurar y sobrescribir",
            "pt": "Reconfigurar e sobrescrever",
            "zh-Hant": "重新設定並覆寫",
        },
    )
    add_translations(
        "返回上一层",
        "Return to gateway menu",
        {
            "ja": "前のメニューに戻る",
            "ko": "이전 메뉴로 돌아가기",
            "ru": "Вернуться в меню шлюза",
            "es": "Volver al menú de pasarela",
            "pt": "Voltar ao menu do gateway",
            "zh-Hant": "返回上一層",
        },
    )
    add_translations(
        "数据库操作",
        "Database operations",
        {
            "ja": "データベース操作",
            "ko": "데이터베이스 작업",
            "ru": "Операции с базами данных",
            "es": "Operaciones de base de datos",
            "pt": "Operações de banco de dados",
            "zh-Hant": "資料庫操作",
        },
    )


_register_menu_translations()


def _register_form_translations() -> None:
    add_translations(
        "项目分析 · 代码生成 · 隔离执行 · 验证 · 集成",
        "Project analysis · code generation · isolated execution · verification · integration",
        {
            "ja": "プロジェクト分析 · コード生成 · 隔離実行 · 検証 · 統合",
            "ko": "프로젝트 분석 · 코드 생성 · 격리 실행 · 검증 · 통합",
            "ru": "Анализ · код · изоляция · проверка · интеграция",
            "es": "Análisis · código · aislamiento · verificación · integración",
            "pt": "Análise · código · isolamento · verificação · integração",
            "zh-Hant": "專案分析 · 程式碼產生 · 隔離執行 · 驗證 · 整合",
        },
    )
    add_translations(
        "输入 `/` 探索命令",
        "Use `/` to explore commands.",
        {
            "ja": "`/` でコマンドを確認できます。",
            "ko": "`/`로 명령을 탐색하세요.",
            "ru": "Введите `/`, чтобы посмотреть команды.",
            "es": "Usa `/` para explorar comandos.",
            "pt": "Use `/` para explorar comandos.",
            "zh-Hant": "輸入 `/` 探索命令。",
        },
    )
    add_translations(
        "模型",
        "Model",
        {
            "ja": "モデル",
            "ko": "모델",
            "ru": "Модель",
            "es": "Modelo",
            "pt": "Modelo",
            "zh-Hant": "模型",
        },
    )
    add_translations(
        "查看当前模型",
        "Show current model",
        {
            "ja": "現在のモデルを表示",
            "ko": "현재 모델 표시",
            "ru": "Показать текущую модель",
            "es": "Mostrar modelo actual",
            "pt": "Mostrar modelo atual",
            "zh-Hant": "查看目前模型",
        },
    )
    add_translations(
        "提供商",
        "Provider",
        {
            "ja": "プロバイダー",
            "ko": "제공자",
            "ru": "Провайдер",
            "es": "Proveedor",
            "pt": "Provedor",
            "zh-Hant": "提供者",
        },
    )
    add_translations(
        "模型名称",
        "Model name",
        {
            "ja": "モデル名",
            "ko": "모델 이름",
            "ru": "Название модели",
            "es": "Nombre del modelo",
            "pt": "Nome do modelo",
            "zh-Hant": "模型名稱",
        },
    )
    add_translations(
        "基础 URL",
        "Base URL",
        {
            "ja": "ベース URL",
            "ko": "기본 URL",
            "ru": "Базовый URL",
            "es": "URL base",
            "pt": "URL base",
            "zh-Hant": "基礎 URL",
        },
    )
    add_translations(
        "API Key 环境变量",
        "API key environment variable",
        {
            "ja": "API キーの環境変数",
            "ko": "API 키 환경 변수",
            "ru": "Переменная окружения с API-ключом",
            "es": "Variable de entorno del API key",
            "pt": "Variável de ambiente da API key",
            "zh-Hant": "API Key 環境變數",
        },
    )
    add_translations(
        "查看状态",
        "Database status",
        {
            "ja": "状態を表示",
            "ko": "상태 보기",
            "ru": "Статус базы данных",
            "es": "Estado de la base de datos",
            "pt": "Status do banco de dados",
            "zh-Hant": "查看狀態",
        },
    )
    add_translations(
        "初始化数据库",
        "Initialize databases",
        {
            "ja": "データベースを初期化",
            "ko": "데이터베이스 초기화",
            "ru": "Инициализировать базы данных",
            "es": "Inicializar bases de datos",
            "pt": "Inicializar bancos de dados",
            "zh-Hant": "初始化資料庫",
        },
    )
    add_translations(
        "备份数据库",
        "Backup databases",
        {
            "ja": "データベースをバックアップ",
            "ko": "데이터베이스 백업",
            "ru": "Создать резервную копию баз данных",
            "es": "Respaldar bases de datos",
            "pt": "Fazer backup dos bancos de dados",
            "zh-Hant": "備份資料庫",
        },
    )
    add_translations(
        "恢复数据库",
        "Restore databases",
        {
            "ja": "データベースを復元",
            "ko": "데이터베이스 복원",
            "ru": "Восстановить базы данных",
            "es": "Restaurar bases de datos",
            "pt": "Restaurar bancos de dados",
            "zh-Hant": "還原資料庫",
        },
    )
    add_translations(
        "新建会话",
        "New session",
        {
            "ja": "新しいセッション",
            "ko": "새 세션",
            "ru": "Новая сессия",
            "es": "Nueva sesión",
            "pt": "Nova sessão",
            "zh-Hant": "新增工作階段",
        },
    )
    add_translations(
        "查看会话历史",
        "Session history",
        {
            "ja": "セッション履歴を表示",
            "ko": "세션 기록 보기",
            "ru": "История сессии",
            "es": "Historial de sesión",
            "pt": "Histórico da sessão",
            "zh-Hant": "查看工作階段歷史",
        },
    )
    add_translations(
        "搜索会话",
        "Session search",
        {
            "ja": "セッションを検索",
            "ko": "세션 검색",
            "ru": "Поиск сессии",
            "es": "Buscar sesión",
            "pt": "Pesquisar sessão",
            "zh-Hant": "搜尋工作階段",
        },
    )
    add_translations(
        "删除会话",
        "Delete session",
        {
            "ja": "セッションを削除",
            "ko": "세션 삭제",
            "ru": "Удалить сессию",
            "es": "Eliminar sesión",
            "pt": "Excluir sessão",
            "zh-Hant": "刪除工作階段",
        },
    )
    add_translations(
        "备份目录",
        "Backup directory",
        {
            "ja": "バックアップ先ディレクトリ",
            "ko": "백업 디렉터리",
            "ru": "Каталог резервной копии",
            "es": "Directorio de respaldo",
            "pt": "Diretório de backup",
            "zh-Hant": "備份目錄",
        },
    )
    add_translations(
        "备份源目录",
        "Backup source directory",
        {
            "ja": "バックアップ元ディレクトリ",
            "ko": "백업 원본 디렉터리",
            "ru": "Исходный каталог резервной копии",
            "es": "Directorio de origen del respaldo",
            "pt": "Diretório de origem do backup",
            "zh-Hant": "備份來源目錄",
        },
    )
    add_translations(
        "恢复目标目录（可选）",
        "Restore target directory (optional)",
        {
            "ja": "復元先ディレクトリ（任意）",
            "ko": "복원 대상 디렉터리(선택)",
            "ru": "Целевой каталог восстановления (необязательно)",
            "es": "Directorio de destino de restauración (opcional)",
            "pt": "Diretório de destino da restauração (opcional)",
            "zh-Hant": "還原目標目錄（選用）",
        },
    )
    add_translations(
        "用户 ID",
        "User id",
        {
            "ja": "ユーザー ID",
            "ko": "사용자 ID",
            "ru": "Идентификатор пользователя",
            "es": "ID de usuario",
            "pt": "ID do usuário",
            "zh-Hant": "使用者 ID",
        },
    )
    add_translations(
        "会话 ID",
        "Session id",
        {
            "ja": "セッション ID",
            "ko": "세션 ID",
            "ru": "Идентификатор сессии",
            "es": "ID de sesión",
            "pt": "ID da sessão",
            "zh-Hant": "工作階段 ID",
        },
    )
    add_translations(
        "FTS5 查询",
        "FTS5 query",
        {
            "ja": "FTS5 クエリ",
            "ko": "FTS5 쿼리",
            "ru": "FTS5-запрос",
            "es": "Consulta FTS5",
            "pt": "Consulta FTS5",
            "zh-Hant": "FTS5 查詢",
        },
    )


_register_form_translations()


def _register_identity_translations() -> None:
    add_translations(
        "我是 SEAM Sprout，一个面向软件项目的自进化 AI 运行时。"
        "我可以分析项目、生成代码、隔离执行、验证并集成变更，"
        "也可以管理任务、存储、日志、模型和 Web 控制台。输入 / 查看命令。",
        "I am SEAM Sprout, a self-evolving AI runtime for software projects. "
        "I can analyze projects, generate code, run it in isolation, verify and "
        "integrate changes, and manage tasks, storage, logs, models, and the web "
        "console. Type / to explore commands.",
        {
            "ja": "私は SEAM Sprout です。分析・生成・隔離実行・検証・統合、"
            "タスク/ストレージ/ログ/モデル/Web 管理ができます。",
            "ko": "저는 SEAM Sprout입니다. 프로젝트 분석, 코드 생성, 격리 실행,"
            "검증, 통합, 작업/저장소/로그/모델/Web 관리를 지원합니다.",
            "ru": "Я SEAM Sprout. Умею анализировать проекты, генерировать код,"
            "изолированно запускать, проверять и интегрировать изменения.",
            "es": "Soy SEAM Sprout. Puedo analizar proyectos, generar código,"
            "ejecutarlo aislado, verificar e integrar cambios.",
            "pt": "Sou o SEAM Sprout. Posso analisar projetos, gerar código,"
            "executar isolado, verificar e integrar mudanças.",
            "zh-Hant": "我是 SEAM Sprout。可分析專案、產生程式碼、隔離執行、"
            "驗證與整合變更。",
        },
    )


_register_identity_translations()
