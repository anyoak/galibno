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

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"          # ← এখানে তোমার বট টোকেন
API_KEY = "YOUR_PROXY_SELLER_API_KEY"         # ← এখানে Proxy-Seller API key
ADMIN_ID = 123456789                          # ← তোমার Telegram numeric user ID

BASE_URL = "https://proxy-seller.com/personal/api/v1"

# Proxy host/port (তোমার প্যানেল থেকে যা আছে সেটাই দাও)
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


# ---------------- PROXY MANAGER ----------------

class ProxyManager:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = BASE_URL

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
                return (
                    "✅ Sub user created successfully.\n\n"
                    f"🆔 Sub User ID: `{package_key}`\n"
                    f"💾 Traffic: {traffic_gb} GB\n"
                    f"📅 Expiry: {expired_at}\n"
                    f"🔧 Status: {'Active' if data.get('is_active') else 'Inactive'}"
                )
            else:
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return f"❌ Error creating sub user: {error_msg}"

        except Exception as e:
            logger.error(f"Create sub user error: {e}", exc_info=True)
            return f"❌ API Error: {str(e)}"

    def delete_sub_user(self, package_key: str) -> str:
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/delete"
            data = {"package_key": package_key}

            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Delete sub user response: {result}")

            if result.get("status") == "success":
                return f"✅ Sub user `{package_key}` deleted successfully."
            else:
                errors = result.get("errors") or []
                error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                return f"❌ Error deleting sub user: {error_msg}"

        except Exception as e:
            logger.error(f"Delete sub user error: {e}", exc_info=True)
            return f"❌ API Error: {str(e)}"

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
                return f"❌ Error: {error_msg}"

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

                    return (
                        "📊 DASHBOARD\n\n"
                        f"🆔 Sub User ID: `{package_key}`\n"
                        f"📅 Expiry: {expired_at}\n"
                        f"🔧 Status: {'🟢 Active' if pkg.get('is_active') else '🔴 Inactive'}\n"
                        f"🔄 Default rotation: {pkg.get('rotation', 'N/A')}s\n\n"
                        "📈 MAIN TRAFFIC:\n"
                        f"• Total: {traffic_limit_gb:.2f} GB\n"
                        f"• Used: {traffic_usage_gb:.2f} GB\n"
                        f"• Left:  {traffic_left_gb:.2f} GB\n\n"
                        "💾 SUB-USER TRAFFIC:\n"
                        f"• Limit: {traffic_limit_sub_gb:.2f} GB\n"
                        f"• Used:  {traffic_usage_sub_gb:.2f} GB\n"
                        f"• Left:  {traffic_left_sub_gb:.2f} GB\n"
                    )

            return "❌ Sub user ID not found under your account."

        except Exception as e:
            logger.error(f"Get package info error: {e}", exc_info=True)
            return f"❌ API Error: {str(e)}"

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
            return False, f"❌ Error fetching lists: {error_msg}"

        except Exception as e:
            logger.error(f"Get subuser lists error: {e}", exc_info=True)
            return False, f"❌ API Error: {str(e)}"

    def change_rotation(self, list_id: int, package_key: str, rotation_value: str) -> str:
        """
        Rotation update করলেও রিটার্নটা একই ফরম্যাটে:
        Your Sub User Id: `...`
        Proxy Connection Details : `host:port:login:password`
        """
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/list/rotation"

            try:
                rotation_int = int(rotation_value)
            except ValueError:
                return "❌ Invalid rotation value. Use only numbers."

            if rotation_int not in [-1, 0] and not (1 <= rotation_int <= 3600):
                return "❌ Rotation must be: -1 (sticky), 0 (per request), or 1–3600 seconds."

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
                return f"❌ Error changing rotation: {error_msg}"

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

            # host/port constant থেকে
            proxy_string = f"{PROXY_HOST}:{PROXY_PORT}:{login}:{password}"

            # চাইলে এখানে rotation info ছোট করে mention করলাম
            if rotation_int == -1:
                rotation_desc = "Sticky"
            elif rotation_int == 0:
                rotation_desc = "Per request"
            else:
                rotation_desc = f"Every {rotation_int}s"

            return (
                f"✅ Rotation Updated ({rotation_desc})\n\n"
                f"Your Sub User Id: `{package_key}`\n"
                f"Proxy Connection Details : `{proxy_string}`"
            )

        except Exception as e:
            logger.error(f"Change rotation error: {e}", exc_info=True)
            return f"❌ API Error: {str(e)}"

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
                        f"{name1}",
                        callback_data=f"country_{c1['code']}_{c1['country']}",
                    )
                )
            if i + 1 < len(page_countries):
                c2 = page_countries[i + 1]
                name2 = c2.get("country", "Unknown")[:18]
                row.append(
                    InlineKeyboardButton(
                        f"{name2}",
                        callback_data=f"country_{c2['code']}_{c2['country']}",
                    )
                )
            if row:
                keyboard.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="current_page"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page + 1}"))
        keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_country")])

        return InlineKeyboardMarkup(keyboard)

    def create_country_list(self, package_key: str, country_code: str, country_name: str) -> str:
        """
        Country select করার পরে ইউজারকে সরাসরি:
        Your Sub User Id: `...`
        Proxy Connection Details : `host:port:login:password`
        এই ফরম্যাটে রিটার্ন।
        """
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
                return f"❌ Error creating IP list: {error_msg}"

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

            return (
                f"Your Sub User Id: `{package_key}`\n"
                f"Proxy Connection Details : `{proxy_string}`"
            )

        except Exception as e:
            logger.error(f"Create country list error: {e}", exc_info=True)
            return f"❌ API Error: {str(e)}"


# Initialize manager
proxy_mgr = ProxyManager(API_KEY)


# ---------------- HANDLERS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        text = (
            "👋 Welcome, Admin.\n\n"
            "🛠 Admin commands:\n"
            "/create - Create sub user\n"
            "/delete - Delete sub user\n"
            "/broadcast <msg> - Broadcast message\n\n"
            "👤 User commands:\n"
            "/dashboard - Check usage\n"
            "/change_rotation - Change rotation for IP list\n"
            "/change_country - Create country-specific IP list\n"
            "/support - Contact support"
        )
    else:
        text = (
            "👋 Welcome to Proxy Manager Bot.\n\n"
            "Available commands:\n"
            "/dashboard - Check your sub user usage\n"
            "/change_rotation - Change rotation of your IP list\n"
            "/change_country - Create country-specific IP list\n"
            "/support - Get help"
        )
    await update.message.reply_text(text)


# --- create sub user ---

async def create_sub_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can create sub users.")
        return ConversationHandler.END

    await update.message.reply_text("📝 Enter traffic for sub user (in GB):")
    return WAITING_GB


async def receive_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gb_amount = update.message.text.strip()

    if not gb_amount.isdigit() or int(gb_amount) <= 0:
        await update.message.reply_text("❌ Please enter a valid positive number (e.g. 5, 10).")
        return WAITING_GB

    await update.message.reply_text("⏳ Creating sub user, please wait...")
    result = proxy_mgr.create_sub_user(gb_amount)
    await update.message.reply_text(result)
    return ConversationHandler.END


# --- delete sub user ---

async def delete_sub_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can delete sub users.")
        return ConversationHandler.END

    await update.message.reply_text("🗑 Enter the sub user ID (package_key) to delete:")
    return WAITING_DELETE_ID


async def receive_delete_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    await update.message.reply_text("⏳ Deleting sub user...")
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
        await update.message.reply_text(f"📢 Broadcast preview:\n\n{message}")
        # এখানে চাইলে ডাটাবেজে user list নিয়ে লুপ করে send করতে পারো
    else:
        await update.message.reply_text("Usage: /broadcast <your_message>")


# --- dashboard ---

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Send your sub user ID (package_key):")
    return WAITING_SUB_USER_ID


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    await update.message.reply_text("⏳ Fetching package information...")
    result = proxy_mgr.get_package_info(package_key)
    await update.message.reply_text(result)
    return ConversationHandler.END


# --- change rotation ---

async def change_rotation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Send your sub user ID (package_key):")
    return WAITING_ROTATION_PACKAGE


async def rotation_receive_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    context.user_data["package_key"] = package_key

    await update.message.reply_text("⏳ Fetching your IP lists...")
    ok, data = proxy_mgr.get_subuser_lists(package_key)

    if not ok:
        await update.message.reply_text(data)
        context.user_data.pop("package_key", None)
        return ConversationHandler.END

    items = data
    if not items:
        await update.message.reply_text("❌ No IP lists found for this sub user.")
        context.user_data.pop("package_key", None)
        return ConversationHandler.END

    if len(items) == 1:
        list_id = items[0].get("id")
        context.user_data["list_id"] = list_id
        await update.message.reply_text(
            "📋 Found one IP list.\n\n"
            "Now send rotation value:\n"
            "-1 = Sticky (no rotation)\n"
            "0 = Per request\n"
            "1–3600 = Seconds"
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
        btn_text = f"ID {list_id} | {country} | {title}"
        keyboard.append(
            [InlineKeyboardButton(btn_text, callback_data=f"rotlist_{list_id}")]
        )

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="rotlist_cancel")])

    await update.message.reply_text(
        "📋 Choose which IP list you want to update rotation for:",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
            "✅ List selected.\n\n"
            "Now send rotation value:\n"
            "-1 = Sticky (no rotation)\n"
            "0 = Rotation per request\n"
            "1–3600 = Rotation by time in seconds"
        )
        return WAITING_ROTATION_VALUE

    return WAITING_ROTATION_LIST


async def perform_rotation_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rotation_value = update.message.text.strip()
    package_key = context.user_data.get("package_key")
    list_id = context.user_data.get("list_id")

    if not package_key or not list_id:
        await update.message.reply_text("❌ Internal error: package/list not found. Please start again.")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text("⏳ Updating rotation...")
    result = proxy_mgr.change_rotation(list_id, package_key, rotation_value)
    await update.message.reply_text(result)

    context.user_data.pop("package_key", None)
    context.user_data.pop("list_id", None)

    return ConversationHandler.END


# --- change country ---

async def change_country_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 Send your sub user ID (package_key):")
    return CHOOSING_COUNTRY


async def ask_country_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    context.user_data["package_key"] = package_key

    reply_markup = proxy_mgr.get_country_keyboard(page=0)

    await update.message.reply_text(
        "🌍 Choose your proxy country.\n"
        "Use Next/Prev buttons to browse, then tap a country.\n"
        "You'll get ready-to-use connection string.",
        reply_markup=reply_markup,
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

        await query.edit_message_text(f"⏳ Creating IP list for {country_name} ({country_code})...")

        result = proxy_mgr.create_country_list(package_key, country_code, country_name)
        await context.bot.send_message(chat_id=query.message.chat_id, text=result)

        context.user_data.pop("package_key", None)
        return ConversationHandler.END

    return CHOOSING_COUNTRY


# --- support / cancel / error ---

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 Support\n\n"
        "For help, contact:\n"
        "👉 @professor_cry\n\n"
        "Available: 24/7"
    )
    await update.message.reply_text(text)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ An internal error occurred. Please try again or contact support.",
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
