import logging
import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIGURATION ----------------

BOT_TOKEN = "8268326998:AAG1Cu7Fv0VTMlQ6Xx8dJVRG20TJRN5Fa3Q"
API_KEY = "de35ee3af144849b4b912b190f3f6f93"
ADMIN_ID = 6577308099

BASE_URL = "https://proxy-seller.com/personal/api/v1"

PROXY_HOST = "res.proxy-seller.com"
PROXY_PORT = 10000

# Conversation states
(
    WAITING_GB,
    WAITING_DELETE_ID,
    WAITING_SUB_USER_ID,
    WAITING_ROTATION_PACKAGE,
    WAITING_ROTATION_LIST,
    WAITING_ROTATION_VALUE,
    CHOOSING_COUNTRY,
) = range(7)

# ---------------- LOGGING ----------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------- MESSAGE STYLES ----------------

class MoonscapeStyle:
    """Moonscape-themed message styling with unique formatting"""
    
    @staticmethod
    def sub_user_created(package_key: str, traffic_gb: str, expired_at: str, is_active: bool) -> str:
        return (
            "🌕 SUB USER CREATED\n\n"
            "╭─────────────────────\n"
            f"│ 🆔 Sub User ID:\n"
            f"│ `{package_key}`\n"
            "│\n"
            f"│ 💾 Traffic: {traffic_gb} GB\n"
            f"│ 📅 Expiry: {expired_at}\n"
            f"│ 🔧 Status: {'🟢 Active' if is_active else '🔴 Inactive'}\n"
            "╰─────────────────────"
        )
    
    @staticmethod
    def proxy_connection(package_key: str, proxy_string: str, additional_info: str = "") -> str:
        message = (
            "🌑 PROXY CONNECTION\n\n"
            "╭─────────────────────\n"
            f"│ 🆔 Sub User ID:\n"
            f"│ `{package_key}`\n"
            "│\n"
            f"│ 🔌 Proxy Details:\n"
            f"│ `{proxy_string}`\n"
            "╰─────────────────────"
        )
        if additional_info:
            message += f"\n\n{additional_info}"
        return message
    
    @staticmethod
    def dashboard_info(package_key: str, expired_at: str, is_active: bool, rotation: str,
                      traffic_limit_gb: float, traffic_usage_gb: float, traffic_left_gb: float,
                      traffic_limit_sub_gb: float, traffic_usage_sub_gb: float, traffic_left_sub_gb: float) -> str:
        return (
            "🌓 DASHBOARD OVERVIEW\n\n"
            "╭─────────────────────\n"
            f"│ 🆔 Sub User ID:\n"
            f"│ `{package_key}`\n"
            "│\n"
            f"│ 📅 Expiry: {expired_at}\n"
            f"│ 🔧 Status: {'🟢 Active' if is_active else '🔴 Inactive'}\n"
            f"│ 🔄 Rotation: {rotation}s\n"
            "╰─────────────────────\n\n"
            "📈 MAIN TRAFFIC\n"
            "╭─────────────────────\n"
            f"│ 📊 Total: {traffic_limit_gb:.2f} GB\n"
            f"│ 📤 Used:  {traffic_usage_gb:.2f} GB\n"
            f"│ 📥 Left:  {traffic_left_gb:.2f} GB\n"
            "╰─────────────────────\n\n"
            "💾 SUB-USER TRAFFIC\n"
            "╭─────────────────────\n"
            f"│ 📊 Limit: {traffic_limit_sub_gb:.2f} GB\n"
            f"│ 📤 Used:  {traffic_usage_sub_gb:.2f} GB\n"
            f"│ 📥 Left:  {traffic_left_sub_gb:.2f} GB\n"
            "╰─────────────────────"
        )
    
    @staticmethod
    def rotation_updated(package_key: str, proxy_string: str, rotation_desc: str) -> str:
        return (
            f"🌗 ROTATION UPDATED ({rotation_desc})\n\n"
            "╭─────────────────────\n"
            f"│ 🆔 Sub User ID:\n"
            f"│ `{package_key}`\n"
            "│\n"
            f"│ 🔌 Proxy Details:\n"
            f"│ `{proxy_string}`\n"
            "╰─────────────────────"
        )
    
    @staticmethod
    def country_list_created(package_key: str, proxy_string: str, country_name: str, country_code: str) -> str:
        return (
            f"🌍 COUNTRY LIST CREATED ({country_code})\n\n"
            "╭─────────────────────\n"
            f"│ 🆔 Sub User ID:\n"
            f"│ `{package_key}`\n"
            "│\n"
            f"│ 🔌 Proxy Details:\n"
            f"│ `{proxy_string}`\n"
            "│\n"
            f"│ 📍 Country: {country_name}\n"
            "╰─────────────────────"
        )
    
    @staticmethod
    def error_message(title: str, description: str) -> str:
        return (
            f"🌒 {title}\n\n"
            "╭─────────────────────\n"
            f"│ ❌ {description}\n"
            "╰─────────────────────"
        )
    
    @staticmethod
    def success_message(title: str, description: str) -> str:
        return (
            f"🌔 {title}\n\n"
            "╭─────────────────────\n"
            f"│ ✅ {description}\n"
            "╰─────────────────────"
        )


# ---------------- PROXY MANAGER ----------------

class ProxyManager:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = BASE_URL
        self.style = MoonscapeStyle()

    # -------- Sub user management --------

    def create_sub_user(self, traffic_gb: str) -> str:
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/create"
            traffic_bytes = int(traffic_gb) * 1024 * 1024 * 1024
            data = {"traffic_limit": str(traffic_bytes)}

            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Create sub user response: {result}")

            if result.get("status") == "success":
                data = result.get("data", {})
                package_key = data.get("package_key", "N/A")
                expired_at = data.get("expired_at", "N/A")
                return self.style.sub_user_created(
                    package_key=package_key,
                    traffic_gb=traffic_gb,
                    expired_at=expired_at,
                    is_active=data.get('is_active', False)
                )
            else:
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return self.style.error_message("CREATE ERROR", error_msg)

        except Exception as e:
            logger.error(f"Create sub user error: {e}", exc_info=True)
            return self.style.error_message("API ERROR", str(e))

    def delete_sub_user(self, package_key: str) -> str:
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/delete"
            data = {"package_key": package_key}

            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Delete sub user response: {result}")

            if result.get("status") == "success":
                return self.style.success_message("SUB USER DELETED", f"`{package_key}` has been deleted successfully.")
            else:
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return self.style.error_message("DELETE ERROR", error_msg)

        except Exception as e:
            logger.error(f"Delete sub user error: {e}", exc_info=True)
            return self.style.error_message("API ERROR", str(e))

    # -------- Dashboard --------

    def get_package_info(self, package_key: str) -> str:
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/packages"
            response = requests.get(url, timeout=30)
            result = response.json()
            logger.info(f"Get package info response: {result}")

            if result.get("status") != "success":
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return self.style.error_message("DASHBOARD ERROR", error_msg)

            for pkg in result.get("data", []):
                if pkg.get("package_key") == package_key:
                    traffic_limit_gb = int(pkg.get("traffic_limit", 0)) / (1024**3)
                    traffic_usage_gb = int(pkg.get("traffic_usage", 0)) / (1024**3)
                    traffic_left_gb = int(pkg.get("traffic_left", 0)) / (1024**3)

                    traffic_limit_sub_gb = int(pkg.get("traffic_limit_sub", 0)) / (1024**3)
                    traffic_usage_sub_gb = int(pkg.get("traffic_usage_sub", 0)) / (1024**3)
                    traffic_left_sub_gb = int(pkg.get("traffic_left_sub", 0)) / (1024**3)

                    expired_at = pkg.get("expired_at", "N/A")
                    if isinstance(expired_at, dict):
                        expired_at = expired_at.get("date", "N/A")

                    return self.style.dashboard_info(
                        package_key=package_key,
                        expired_at=expired_at,
                        is_active=pkg.get('is_active', False),
                        rotation=pkg.get('rotation', 'N/A'),
                        traffic_limit_gb=traffic_limit_gb,
                        traffic_usage_gb=traffic_usage_gb,
                        traffic_left_gb=traffic_left_gb,
                        traffic_limit_sub_gb=traffic_limit_sub_gb,
                        traffic_usage_sub_gb=traffic_usage_sub_gb,
                        traffic_left_sub_gb=traffic_left_sub_gb
                    )

            return self.style.error_message("NOT FOUND", "Sub user ID not found under your account.")

        except Exception as e:
            logger.error(f"Get package info error: {e}", exc_info=True)
            return self.style.error_message("API ERROR", str(e))

    # -------- Lists --------

    def get_subuser_lists(self, package_key: str):
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/lists"
            params = {"package_key": package_key}
            response = requests.get(url, params=params, timeout=30)
            result = response.json()
            logger.info(f"Get subuser lists response: {result}")

            if result.get("status") == "success":
                data = result.get("data") or {}
                return True, data.get("items") or []

            errors = result.get("errors") or []
            error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
            return False, error_msg

        except Exception as e:
            logger.error(f"Get subuser lists error: {e}", exc_info=True)
            return False, str(e)

    def change_rotation(self, list_id: int, package_key: str, rotation_value: str) -> str:
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/list/rotation"

            try:
                rotation_int = int(rotation_value)
            except ValueError:
                return self.style.error_message("INVALID INPUT", "Please use only numbers for rotation value.")

            if rotation_int not in [-1, 0] and not (1 <= rotation_int <= 3600):
                return self.style.error_message("INVALID ROTATION", "Rotation must be: -1 (sticky), 0 (per request), or 1–3600 seconds.")

            data = {
                "id": list_id,
                "rotation": rotation_int,
                "package_key": package_key,
            }

            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Change rotation response: {result}")

            if result.get("status") != "success":
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return self.style.error_message("ROTATION ERROR", error_msg)

            data = result.get("data") or {}
            geo_raw = data.get("geo") or {}
            export_raw = data.get("export") or {}

            # geo normalize
            if isinstance(geo_raw, list):
                geo = geo_raw[0] if geo_raw else {}
            elif isinstance(geo_raw, dict):
                geo = geo_raw
            else:
                geo = {}

            export = export_raw if isinstance(export_raw, dict) else {}

            login = data.get("login", "N/A")
            password = data.get("password", "N/A")

            proxy_string = f"{PROXY_HOST}:{PROXY_PORT}:{login}:{password}"

            if rotation_int == -1:
                rotation_desc = "Sticky"
            elif rotation_int == 0:
                rotation_desc = "Per request"
            else:
                rotation_desc = f"Every {rotation_int}s"

            return self.style.rotation_updated(
                package_key=package_key,
                proxy_string=proxy_string,
                rotation_desc=rotation_desc
            )

        except Exception as e:
            logger.error(f"Change rotation error: {e}", exc_info=True)
            return self.style.error_message("API ERROR", str(e))

    # -------- Country list / geo --------

    def get_available_countries(self):
        try:
            url = f"{self.base_url}/{self.api_key}/resident/geo"
            response = requests.get(url, timeout=30)
            result = response.json()
            logger.info(f"Get GEO countries response: {result}")

            if isinstance(result, list):
                raw_list = result
            elif isinstance(result, dict) and isinstance(result.get("data"), list):
                raw_list = result["data"]
            else:
                return self.get_worldwide_countries()

            countries = []
            for item in raw_list:
                code = item.get("code")
                name = item.get("name")
                if code and name:
                    countries.append({"country": name, "code": code})

            return countries or self.get_worldwide_countries()

        except Exception as e:
            logger.error(f"Get countries error: {e}", exc_info=True)
            return self.get_worldwide_countries()

    def get_worldwide_countries(self):
        return [
            {"country": "United States", "code": "US"},
            {"country": "United Kingdom", "code": "GB"},
            {"country": "Canada", "code": "CA"},
            {"country": "Germany", "code": "DE"},
            {"country": "France", "code": "FR"},
            {"country": "Italy", "code": "IT"},
            {"country": "Spain", "code": "ES"},
            {"country": "Netherlands", "code": "NL"},
            {"country": "Sweden", "code": "SE"},
            {"country": "Switzerland", "code": "CH"},
            {"country": "Norway", "code": "NO"},
            {"country": "Denmark", "code": "DK"},
            {"country": "Finland", "code": "FI"},
            {"country": "Belgium", "code": "BE"},
            {"country": "Austria", "code": "AT"},
            {"country": "Ireland", "code": "IE"},
            {"country": "Portugal", "code": "PT"},
            {"country": "Poland", "code": "PL"},
            {"country": "Czech Republic", "code": "CZ"},
            {"country": "Hungary", "code": "HU"},
            {"country": "Romania", "code": "RO"},
            {"country": "Greece", "code": "GR"},
            {"country": "Bulgaria", "code": "BG"},
            {"country": "Slovakia", "code": "SK"},
            {"country": "Croatia", "code": "HR"},
            {"country": "Lithuania", "code": "LT"},
            {"country": "Slovenia", "code": "SI"},
            {"country": "Latvia", "code": "LV"},
            {"country": "Estonia", "code": "EE"},
            {"country": "Cyprus", "code": "CY"},
            {"country": "Luxembourg", "code": "LU"},
            {"country": "Malta", "code": "MT"},
            {"country": "Australia", "code": "AU"},
            {"country": "New Zealand", "code": "NZ"},
            {"country": "Japan", "code": "JP"},
            {"country": "South Korea", "code": "KR"},
            {"country": "Singapore", "code": "SG"},
            {"country": "Hong Kong", "code": "HK"},
            {"country": "Taiwan", "code": "TW"},
            {"country": "India", "code": "IN"},
            {"country": "Brazil", "code": "BR"},
            {"country": "Mexico", "code": "MX"},
            {"country": "Argentina", "code": "AR"},
            {"country": "Chile", "code": "CL"},
            {"country": "Colombia", "code": "CO"},
            {"country": "Peru", "code": "PE"},
            {"country": "South Africa", "code": "ZA"},
            {"country": "Egypt", "code": "EG"},
            {"country": "Israel", "code": "IL"},
            {"country": "Turkey", "code": "TR"},
            {"country": "Saudi Arabia", "code": "SA"},
            {"country": "United Arab Emirates", "code": "AE"},
            {"country": "Qatar", "code": "QA"},
            {"country": "Kuwait", "code": "KW"},
            {"country": "Thailand", "code": "TH"},
            {"country": "Malaysia", "code": "MY"},
            {"country": "Indonesia", "code": "ID"},
            {"country": "Philippines", "code": "PH"},
            {"country": "Vietnam", "code": "VN"},
            {"country": "Pakistan", "code": "PK"},
            {"country": "Bangladesh", "code": "BD"},
            {"country": "Sri Lanka", "code": "LK"},
            {"country": "Russia", "code": "RU"},
            {"country": "Ukraine", "code": "UA"},
            {"country": "Belarus", "code": "BY"},
            {"country": "Kazakhstan", "code": "KZ"},
            {"country": "Georgia", "code": "GE"},
            {"country": "Azerbaijan", "code": "AZ"},
            {"country": "Armenia", "code": "AM"},
            {"country": "Morocco", "code": "MA"},
            {"country": "Algeria", "code": "DZ"},
            {"country": "Tunisia", "code": "TN"},
            {"country": "Kenya", "code": "KE"},
            {"country": "Nigeria", "code": "NG"},
            {"country": "Ghana", "code": "GH"},
            {"country": "Ethiopia", "code": "ET"},
            {"country": "Uganda", "code": "UG"},
            {"country": "Tanzania", "code": "TZ"},
            {"country": "Zambia", "code": "ZM"},
            {"country": "Zimbabwe", "code": "ZW"},
            {"country": "Botswana", "code": "BW"},
            {"country": "Namibia", "code": "NA"},
            {"country": "Senegal", "code": "SN"},
            {"country": "Ivory Coast", "code": "CI"},
            {"country": "Cameroon", "code": "CM"},
            {"country": "Angola", "code": "AO"},
            {"country": "Sudan", "code": "SD"},
            {"country": "Venezuela", "code": "VE"},
            {"country": "Ecuador", "code": "EC"},
            {"country": "Costa Rica", "code": "CR"},
            {"country": "Panama", "code": "PA"},
            {"country": "Dominican Republic", "code": "DO"},
            {"country": "Guatemala", "code": "GT"},
            {"country": "El Salvador", "code": "SV"},
            {"country": "Honduras", "code": "HN"},
            {"country": "Nicaragua", "code": "NI"},
            {"country": "Paraguay", "code": "PY"},
            {"country": "Uruguay", "code": "UY"},
            {"country": "Bolivia", "code": "BO"},
            {"country": "Jamaica", "code": "JM"},
            {"country": "Trinidad and Tobago", "code": "TT"},
            {"country": "Bahamas", "code": "BS"},
            {"country": "Barbados", "code": "BB"},
            {"country": "Iceland", "code": "IS"},
            {"country": "Albania", "code": "AL"},
            {"country": "Bosnia and Herzegovina", "code": "BA"},
            {"country": "North Macedonia", "code": "MK"},
            {"country": "Montenegro", "code": "ME"},
            {"country": "Serbia", "code": "RS"},
            {"country": "Moldova", "code": "MD"},
            {"country": "Kosovo", "code": "XK"},
            {"country": "Andorra", "code": "AD"},
            {"country": "Liechtenstein", "code": "LI"},
            {"country": "Monaco", "code": "MC"},
            {"country": "San Marino", "code": "SM"},
            {"country": "Vatican City", "code": "VA"},
            {"country": "Mauritius", "code": "MU"},
            {"country": "Seychelles", "code": "SC"},
            {"country": "Maldives", "code": "MV"},
            {"country": "Fiji", "code": "FJ"},
            {"country": "Papua New Guinea", "code": "PG"},
            {"country": "Cambodia", "code": "KH"},
            {"country": "Laos", "code": "LA"},
            {"country": "Myanmar", "code": "MM"},
            {"country": "Mongolia", "code": "MN"},
            {"country": "Nepal", "code": "NP"},
            {"country": "Bhutan", "code": "BT"},
            {"country": "Brunei", "code": "BN"},
            {"country": "Timor-Leste", "code": "TL"},
            {"country": "Macao", "code": "MO"},
            {"country": "Oman", "code": "OM"},
            {"country": "Bahrain", "code": "BH"},
            {"country": "Jordan", "code": "JO"},
            {"country": "Lebanon", "code": "LB"},
            {"country": "Syria", "code": "SY"},
            {"country": "Iraq", "code": "IQ"},
            {"country": "Yemen", "code": "YE"},
            {"country": "Afghanistan", "code": "AF"},
            {"country": "Pakistan", "code": "PK"},
            {"country": "Sri Lanka", "code": "LK"},
            {"country": "Bangladesh", "code": "BD"},
            {"country": "Mali", "code": "ML"},
            {"country": "Niger", "code": "NE"},
            {"country": "Chad", "code": "TD"},
            {"country": "Sudan", "code": "SD"},
            {"country": "Eritrea", "code": "ER"},
            {"country": "Djibouti", "code": "DJ"},
            {"country": "Somalia", "code": "SO"},
            {"country": "Rwanda", "code": "RW"},
            {"country": "Burundi", "code": "BI"},
            {"country": "Malawi", "code": "MW"},
            {"country": "Zambia", "code": "ZM"},
            {"country": "Zimbabwe", "code": "ZW"},
            {"country": "Botswana", "code": "BW"},
            {"country": "Namibia", "code": "NA"},
            {"country": "Lesotho", "code": "LS"},
            {"country": "Eswatini", "code": "SZ"},
            {"country": "Madagascar", "code": "MG"},
            {"country": "Mauritania", "code": "MR"},
            {"country": "Benin", "code": "BJ"},
            {"country": "Togo", "code": "TG"},
            {"country": "Burkina Faso", "code": "BF"},
            {"country": "Sierra Leone", "code": "SL"},
            {"country": "Liberia", "code": "LR"},
            {"country": "Guinea", "code": "GN"},
            {"country": "Guinea-Bissau", "code": "GW"},
            {"country": "Gambia", "code": "GM"},
            {"country": "Cape Verde", "code": "CV"},
            {"country": "Comoros", "code": "KM"},
            {"country": "Sao Tome and Principe", "code": "ST"},
            {"country": "Equatorial Guinea", "code": "GQ"},
            {"country": "Gabon", "code": "GA"},
            {"country": "Republic of Congo", "code": "CG"},
            {"country": "DR Congo", "code": "CD"},
            {"country": "Central African Republic", "code": "CF"},
            {"country": "South Sudan", "code": "SS"}
        ]

    def get_country_keyboard(self, page: int = 0, countries_per_page: int = 10) -> InlineKeyboardMarkup:
        countries = self.get_available_countries()
        total_pages = (len(countries) + countries_per_page - 1) // countries_per_page

        start_idx = page * countries_per_page
        end_idx = start_idx + countries_per_page
        page_countries = countries[start_idx:end_idx]

        keyboard = []

        for i in range(0, len(page_countries), 2):
            row = []
            if i < len(page_countries):
                c1 = page_countries[i]
                name1 = c1.get("country", "Unknown")[:18]
                row.append(
                    InlineKeyboardButton(
                        f"🌍 {name1}",
                        callback_data=f"country_{c1['code']}_{c1['country']}",
                    )
                )
            if i + 1 < len(page_countries):
                c2 = page_countries[i + 1]
                name2 = c2.get("country", "Unknown")[:18]
                row.append(
                    InlineKeyboardButton(
                        f"🌍 {name2}",
                        callback_data=f"country_{c2['code']}_{c2['country']}",
                    )
                )
            if row:
                keyboard.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="current_page"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page + 1}"))
        keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_country")])

        return InlineKeyboardMarkup(keyboard)

    def create_country_list(self, package_key: str, country_code: str, country_name: str) -> str:
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/list/add"

            data = {
                "title": f"{country_name} Residential List",
                "whitelist": "",
                "geo": {"country": country_code},
                "export": {"ports": 100, "ext": "txt"},
                "rotation": -1,
                "package_key": package_key,
            }

            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Create country list response: {result}")

            if result.get("status") != "success":
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return self.style.error_message("LIST CREATION ERROR", error_msg)

            data = result.get("data") or {}
            geo_raw = data.get("geo") or {}
            export_raw = data.get("export") or {}

            if isinstance(geo_raw, list):
                geo = geo_raw[0] if geo_raw else {}
            elif isinstance(geo_raw, dict):
                geo = geo_raw
            else:
                geo = {}

            export = export_raw if isinstance(export_raw, dict) else {}

            login = data.get("login", "N/A")
            password = data.get("password", "N/A")

            proxy_string = f"{PROXY_HOST}:{PROXY_PORT}:{login}:{password}"

            return self.style.country_list_created(
                package_key=package_key,
                proxy_string=proxy_string,
                country_name=country_name,
                country_code=country_code
            )

        except Exception as e:
            logger.error(f"Create country list error: {e}", exc_info=True)
            return self.style.error_message("API ERROR", str(e))


# Initialize manager
proxy_mgr = ProxyManager(API_KEY)


# ---------------- HANDLERS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        text = (
            "🌕 WELCOME ADMIN\n\n"
            "╭─────────────────────\n"
            "│ 🛠 Admin Commands:\n"
            "│ /create - Create sub user\n"
            "│ /delete - Delete sub user\n"
            "│ /broadcast - Broadcast message\n"
            "│\n"
            "│ 👤 User Commands:\n"
            "│ /dashboard - Check usage\n"
            "│ /change_rotation - Change rotation\n"
            "│ /change_country - Country IP list\n"
            "│ /support - Contact support\n"
            "╰─────────────────────"
        )
    else:
        text = (
            "🌕 WELCOME TO PROXY MANAGER\n\n"
            "╭─────────────────────\n"
            "│ 📋 Available Commands:\n"
            "│ /dashboard - Check usage\n"
            "│ /change_rotation - Change rotation\n"
            "│ /change_country - Country IP list\n"
            "│ /support - Get help\n"
            "╰─────────────────────"
        )
    await update.message.reply_text(text)


# --- create sub user ---

async def create_sub_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can create sub users.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🌕 CREATE SUB USER\n\n"
        "╭─────────────────────\n"
        "│ 💾 Enter traffic amount in GB:\n"
        "│ (e.g., 5, 10, 20)\n"
        "╰─────────────────────"
    )
    return WAITING_GB


async def receive_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gb_amount = update.message.text.strip()

    if not gb_amount.isdigit() or int(gb_amount) <= 0:
        await update.message.reply_text(
            "🌒 INVALID INPUT\n\n"
            "╭─────────────────────\n"
            "│ ❌ Please enter a valid positive number\n"
            "│ Example: 5, 10, 20\n"
            "╰─────────────────────"
        )
        return WAITING_GB

    await update.message.reply_text(
        "🌗 CREATING SUB USER\n\n"
        "╭─────────────────────\n"
        "│ ⏳ Please wait...\n"
        "╰─────────────────────"
    )
    result = proxy_mgr.create_sub_user(gb_amount)
    await update.message.reply_text(result)
    return ConversationHandler.END


# --- delete sub user ---

async def delete_sub_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can delete sub users.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🌕 DELETE SUB USER\n\n"
        "╭─────────────────────\n"
        "│ 🗑 Enter sub user ID to delete:\n"
        "│ (package_key)\n"
        "╰─────────────────────"
    )
    return WAITING_DELETE_ID


async def receive_delete_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    await update.message.reply_text(
        "🌗 DELETING SUB USER\n\n"
        "╭─────────────────────\n"
        "│ ⏳ Please wait...\n"
        "╰─────────────────────"
    )
    result = proxy_mgr.delete_sub_user(package_key)
    await update.message.reply_text(result)
    return ConversationHandler.END


# --- broadcast ---

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can use /broadcast.")
        return

    if context.args:
        message = " ".join(context.args)
        await update.message.reply_text(
            f"📢 BROADCAST PREVIEW\n\n"
            f"╭─────────────────────\n"
            f"│ {message}\n"
            f"╰─────────────────────"
        )
    else:
        await update.message.reply_text("Usage: /broadcast <your_message>")


# --- dashboard ---

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌕 DASHBOARD\n\n"
        "╭─────────────────────\n"
        "│ 📊 Send your sub user ID:\n"
        "│ (package_key)\n"
        "╰─────────────────────"
    )
    return WAITING_SUB_USER_ID


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    await update.message.reply_text(
        "🌗 FETCHING DATA\n\n"
        "╭─────────────────────\n"
        "│ ⏳ Please wait...\n"
        "╰─────────────────────"
    )
    result = proxy_mgr.get_package_info(package_key)
    await update.message.reply_text(result)
    return ConversationHandler.END


# --- change rotation ---

async def change_rotation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌕 CHANGE ROTATION\n\n"
        "╭─────────────────────\n"
        "│ 🔄 Send your sub user ID:\n"
        "│ (package_key)\n"
        "╰─────────────────────"
    )
    return WAITING_ROTATION_PACKAGE


async def rotation_receive_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    context.user_data["package_key"] = package_key

    await update.message.reply_text(
        "🌗 FETCHING IP LISTS\n\n"
        "╭─────────────────────\n"
        "│ ⏳ Please wait...\n"
        "╰─────────────────────"
    )
    ok, data = proxy_mgr.get_subuser_lists(package_key)

    if not ok:
        await update.message.reply_text(proxy_mgr.style.error_message("FETCH ERROR", data))
        context.user_data.pop("package_key", None)
        return ConversationHandler.END

    items = data
    if not items:
        await update.message.reply_text(proxy_mgr.style.error_message("NO LISTS", "No IP lists found for this sub user."))
        context.user_data.pop("package_key", None)
        return ConversationHandler.END

    if len(items) == 1:
        list_id = items[0].get("id")
        context.user_data["list_id"] = list_id
        await update.message.reply_text(
            "🌕 SELECT ROTATION\n\n"
            "╭─────────────────────\n"
            "│ 🔄 Choose rotation value:\n"
            "│ -1 = Sticky (no rotation)\n"
            "│ 0 = Per request\n"
            "│ 1–3600 = Seconds\n"
            "╰─────────────────────"
        )
        return WAITING_ROTATION_VALUE

    keyboard = []
    for item in items:
        list_id = item.get("id")
        title = item.get("title", "N/A")[:30]
        geo = item.get("geo") or {}
        if isinstance(geo, list):
            geo = geo[0] if geo else {}
        country = geo.get("country", "Any")
        btn_text = f"🌐 ID {list_id} | {country}"
        keyboard.append(
            [InlineKeyboardButton(btn_text, callback_data=f"rotlist_{list_id}")]
        )

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="rotlist_cancel")])

    await update.message.reply_text(
        "🌕 SELECT IP LIST\n\n"
        "╭─────────────────────\n"
        "│ 📋 Choose IP list to update:\n"
        "╰─────────────────────",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_ROTATION_LIST


async def handle_rotation_list_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "rotlist_cancel":
        context.user_data.pop("package_key", None)
        context.user_data.pop("list_id", None)
        await query.edit_message_text("❌ Rotation change cancelled.")
        return ConversationHandler.END

    if data.startswith("rotlist_"):
        try:
            list_id = int(data.split("_", 1)[1])
        except ValueError:
            await query.edit_message_text("❌ Invalid list selection.")
            context.user_data.pop("package_key", None)
            return ConversationHandler.END

        context.user_data["list_id"] = list_id
        await query.edit_message_text(
            "🌕 SET ROTATION\n\n"
            "╭─────────────────────\n"
            "│ 🔄 Send rotation value:\n"
            "│ -1 = Sticky\n"
            "│ 0 = Per request\n"
            "│ 1–3600 = Seconds\n"
            "╰─────────────────────"
        )
        return WAITING_ROTATION_VALUE

    return WAITING_ROTATION_LIST


async def perform_rotation_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rotation_value = update.message.text.strip()
    package_key = context.user_data.get("package_key")
    list_id = context.user_data.get("list_id")

    if not package_key or not list_id:
        await update.message.reply_text(proxy_mgr.style.error_message("ERROR", "Package/list not found. Please start again."))
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(
        "🌗 UPDATING ROTATION\n\n"
        "╭─────────────────────\n"
        "│ ⏳ Please wait...\n"
        "╰─────────────────────"
    )
    result = proxy_mgr.change_rotation(list_id, package_key, rotation_value)
    await update.message.reply_text(result)

    context.user_data.pop("package_key", None)
    context.user_data.pop("list_id", None)

    return ConversationHandler.END


# --- change country ---

async def change_country_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌕 CHANGE COUNTRY\n\n"
        "╭─────────────────────\n"
        "│ 🌍 Send your sub user ID:\n"
        "│ (package_key)\n"
        "╰─────────────────────"
    )
    return CHOOSING_COUNTRY


async def ask_country_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    context.user_data["package_key"] = package_key

    reply_markup = proxy_mgr.get_country_keyboard(page=0)

    await update.message.reply_text(
        "🌕 SELECT COUNTRY\n\n"
        "╭─────────────────────\n"
        "│ 🌍 Choose proxy country\n"
        "│ Use Next/Prev to browse\n"
        "│ Tap country for connection\n"
        "╰─────────────────────",
        reply_markup=reply_markup
    )

    return CHOOSING_COUNTRY


async def handle_country_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "cancel_country":
        context.user_data.pop("package_key", None)
        await query.edit_message_text("❌ Country selection cancelled.")
        return ConversationHandler.END

    if data.startswith("page_"):
        try:
            page = int(data.split("_")[1])
        except ValueError:
            page = 0
        reply_markup = proxy_mgr.get_country_keyboard(page=page)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return CHOOSING_COUNTRY

    if data.startswith("country_"):
        parts = data.split("_", 2)
        if len(parts) != 3:
            await query.edit_message_text("❌ Invalid country data.")
            context.user_data.pop("package_key", None)
            return ConversationHandler.END

        country_code = parts[1]
        country_name = parts[2]
        package_key = context.user_data.get("package_key")

        if not package_key:
            await query.edit_message_text("❌ Sub user ID missing. Please start again.")
            return ConversationHandler.END

        await query.edit_message_text(
            f"🌗 CREATING IP LIST\n\n"
            f"╭─────────────────────\n"
            f"│ ⏳ Creating list for {country_name}...\n"
            f"╰─────────────────────"
        )

        result = proxy_mgr.create_country_list(package_key, country_code, country_name)
        await context.bot.send_message(chat_id=query.message.chat_id, text=result)

        context.user_data.pop("package_key", None)
        return ConversationHandler.END

    return CHOOSING_COUNTRY


# --- support / cancel / error ---

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🌕 SUPPORT\n\n"
        "╭─────────────────────\n"
        "│ 🆘 For help contact:\n"
        "│ 👉 @professor_cry\n"
        "│\n"
        "│ 🕐 Available: 24/7\n"
        "╰─────────────────────"
    )
    await update.message.reply_text(text)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🌒 OPERATION CANCELLED\n\n"
        "╭─────────────────────\n"
        "│ ❌ Operation cancelled\n"
        "╰─────────────────────"
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=proxy_mgr.style.error_message("INTERNAL ERROR", "Please try again or contact support.")
            )
    except Exception:
        pass


# ---------------- MAIN ----------------

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_error_handler(error_handler)

    create_conv = ConversationHandler(
        entry_points=[CommandHandler("create", create_sub_user_cmd)],
        states={WAITING_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gb)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_sub_user_cmd)],
        states={WAITING_DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_id)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dashboard_conv = ConversationHandler(
        entry_points=[CommandHandler("dashboard", dashboard)],
        states={WAITING_SUB_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_dashboard)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    rotation_conv = ConversationHandler(
        entry_points=[CommandHandler("change_rotation", change_rotation_cmd)],
        states={
            WAITING_ROTATION_PACKAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rotation_receive_package)
            ],
            WAITING_ROTATION_LIST: [
                CallbackQueryHandler(handle_rotation_list_choice, pattern=r"^rotlist_")
            ],
            WAITING_ROTATION_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, perform_rotation_change)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    country_conv = ConversationHandler(
        entry_points=[CommandHandler("change_country", change_country_cmd)],
        states={
            CHOOSING_COUNTRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_country_choice),
                CallbackQueryHandler(
                    handle_country_selection,
                    pattern=r"^(country_|page_|cancel_country|current_page)",
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler("broadcast", broadcast))

    application.add_handler(create_conv)
    application.add_handler(delete_conv)
    application.add_handler(dashboard_conv)
    application.add_handler(rotation_conv)
    application.add_handler(country_conv)

    logger.info("🤖 Proxy Manager Bot starting...")
    logger.info(f"🔧 Admin ID: {ADMIN_ID}")

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()