import requests
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration - Your actual credentials
BOT_TOKEN = "8268326998:AAG1Cu7Fv0VTMlQ6Xx8dJVRG20TJRN5Fa3Q"
API_KEY = "de35ee3af144849b4b912b190f3f6f93"
ADMIN_ID = 6577308099

BASE_URL = "https://proxy-seller.com/personal/api/v1"

# Conversation states
WAITING_GB, WAITING_DELETE_ID, WAITING_SUB_USER_ID, WAITING_ROTATION, CHOOSING_COUNTRY = range(5)

class ProxyManager:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = BASE_URL
    
    def create_sub_user(self, traffic_gb):
        """Create sub user with specified traffic in GB"""
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/create"
            
            # Convert GB to bytes
            traffic_bytes = int(traffic_gb) * 1024 * 1024 * 1024
            
            data = {"traffic_limit": str(traffic_bytes)}
            
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Create sub user response: {result}")
            
            if result.get('status') == 'success':
                package_key = result['data']['package_key']
                return f"✅ Sub User Created Successfully!\n\n🆔 ID: {package_key}\n💾 Traffic: {traffic_gb} GB\n🔧 Status: Active"
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                return f"❌ Error: {error_msg}"
                
        except Exception as e:
            logger.error(f"Create sub user error: {e}")
            return f"❌ API Error: {str(e)}"
    
    def delete_sub_user(self, package_key):
        """Delete sub user by package key"""
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/delete"
            data = {"package_key": package_key}
            
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Delete sub user response: {result}")
            
            if result.get('status') == 'success':
                return f"✅ Sub User {package_key} Deleted Successfully!"
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                return f"❌ Error: {error_msg}"
                
        except Exception as e:
            logger.error(f"Delete sub user error: {e}")
            return f"❌ API Error: {str(e)}"
    
    def get_package_info(self, package_key):
        """Get package information for dashboard"""
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/packages"
            
            response = requests.get(url, timeout=30)
            result = response.json()
            logger.info(f"Get package info response: {result}")
            
            if result.get('status') == 'success':
                packages = result.get('data', [])
                
                for package in packages:
                    if package.get('package_key') == package_key:
                        # Convert bytes to GB
                        traffic_limit_gb = int(package.get('traffic_limit', 0)) / (1024**3)
                        traffic_usage_gb = int(package.get('traffic_usage', 0)) / (1024**3)
                        traffic_left_gb = int(package.get('traffic_left', 0)) / (1024**3)
                        
                        # Handle expired_at which can be a dictionary
                        expired_at = package.get('expired_at', 'N/A')
                        if isinstance(expired_at, dict):
                            expired_at = expired_at.get('date', 'N/A')
                        
                        dashboard_text = f"""
📊 DASHBOARD

🆔 User ID: {package_key}
🔄 Rotation: {package.get('rotation', 'N/A')}s
📅 Expiry: {expired_at}
🔧 Status: {'🟢 Active' if package.get('is_active') else '🔴 Inactive'}

📈 TRAFFIC USAGE:
├── Total: {traffic_limit_gb:.2f} GB
├── Used: {traffic_usage_gb:.2f} GB  
└── Available: {traffic_left_gb:.2f} GB

💾 SUB-USER TRAFFIC:
├── Limit: {int(package.get('traffic_limit_sub', 0)) / (1024**3):.2f} GB
├── Used: {int(package.get('traffic_usage_sub', 0)) / (1024**3):.2f} GB
└── Left: {int(package.get('traffic_left_sub', 0)) / (1024**3):.2f} GB
                        """
                        return dashboard_text
                
                return "❌ Sub User ID not found in your packages!"
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                return f"❌ Error: {error_msg}"
                
        except Exception as e:
            logger.error(f"Get package info error: {e}")
            return f"❌ API Error: {str(e)}"
    
    def change_rotation(self, package_key, rotation_value):
        """Change rotation timing for sub user"""
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/list/rotation"
            
            # Convert rotation value to integer
            try:
                rotation_int = int(rotation_value)
            except ValueError:
                return "❌ Invalid rotation value. Please use numbers only."
            
            # Validate rotation range
            if rotation_int not in [-1, 0] and not (1 <= rotation_int <= 3600):
                return "❌ Rotation must be: -1 (rotation), 0 (per request), or 1-3600 seconds"
            
            data = {
                "package_key": package_key, 
                "rotation": rotation_int
            }
            
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Change rotation response: {result}")
            
            if result.get('status') == 'success':
                data = result['data']
                geo = data.get('geo', {})
                
                # Determine rotation description
                rotation_desc = ""
                if rotation_int == -1:
                    rotation_desc = "Continuous rotation"
                elif rotation_int == 0:
                    rotation_desc = "Rotation per request"
                else:
                    rotation_desc = f"Rotation every {rotation_int} seconds"
                
                proxy_info = f"""
🔄 ROTATION CHANGED SUCCESSFULLY!

⚙️ Rotation Setting: {rotation_desc}

🌍 CURRENT LOCATION:
• Country: {geo.get('country', 'N/A')}
• Region: {geo.get('region', 'N/A')} 
• City: {geo.get('city', 'N/A')}
• ISP: {geo.get('isp', 'N/A')}

🔧 CONNECTION DETAILS:
• Host: {data.get('login', 'N/A')}
• Port: {data.get('export', {}).get('ports', 'N/A')}
• Username: {data.get('login', 'N/A')}
• Password: {data.get('password', 'N/A')}

🔗 CONNECTION STRING:
{data.get('login', 'N/A')}:{data.get('password', 'N/A')}@{data.get('login', 'N/A')}:{data.get('export', {}).get('ports', 'N/A')}

📝 Whitelist: {data.get('whitelist', 'Not set')}
                """
                return proxy_info
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                return f"❌ Error: {error_msg}"
                
        except Exception as e:
            logger.error(f"Change rotation error: {e}")
            return f"❌ API Error: {str(e)}"

    def get_available_countries(self):
        """Get list of available countries from ProxySeller"""
        try:
            # This endpoint might need to be adjusted based on actual ProxySeller API
            url = f"{self.base_url}/{self.api_key}/resident/geo/country"
            
            response = requests.get(url, timeout=30)
            result = response.json()
            logger.info(f"Get countries response: {result}")
            
            if result.get('status') == 'success':
                return result.get('data', [])
            else:
                # Return worldwide countries if API fails
                return self.get_worldwide_countries()
                
        except Exception as e:
            logger.error(f"Get countries error: {e}")
            # Return worldwide countries if API fails
            return self.get_worldwide_countries()
    
    def get_worldwide_countries(self):
        """Return comprehensive list of worldwide countries"""
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
    
    def get_country_keyboard(self, page=0, countries_per_page=10):
        """Get paginated country keyboard"""
        countries = self.get_available_countries()
        total_pages = (len(countries) + countries_per_page - 1) // countries_per_page
        
        start_idx = page * countries_per_page
        end_idx = start_idx + countries_per_page
        page_countries = countries[start_idx:end_idx]
        
        keyboard = []
        
        # Add countries in rows of 2
        for i in range(0, len(page_countries), 2):
            row = []
            if i < len(page_countries):
                country1 = page_countries[i]
                country_name1 = country1.get('country', 'Unknown')[:15]  # Limit name length
                button1 = InlineKeyboardButton(
                    f"🌍 {country_name1}", 
                    callback_data=f"country_{country1['code']}_{country1['country']}"
                )
                row.append(button1)
            
            if i + 1 < len(page_countries):
                country2 = page_countries[i + 1]
                country_name2 = country2.get('country', 'Unknown')[:15]  # Limit name length
                button2 = InlineKeyboardButton(
                    f"🌍 {country_name2}", 
                    callback_data=f"country_{country2['code']}_{country2['country']}"
                )
                row.append(button2)
            
            if row:
                keyboard.append(row)
        
        # Navigation buttons
        navigation_row = []
        if page > 0:
            navigation_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"page_{page-1}"))
        
        navigation_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="current_page"))
        
        if page < total_pages - 1:
            navigation_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
        
        if navigation_row:
            keyboard.append(navigation_row)
        
        # Cancel button
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_country")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def create_country_list(self, package_key, country_code, country_name):
        """Create a new proxy list for specific country"""
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/list/add"
            
            data = {
                "package_key": package_key,
                "country": country_code,
                "title": f"{country_name} Proxy List"
            }
            
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Create country list response: {result}")
            
            if result.get('status') == 'success':
                data = result['data']
                geo = data.get('geo', {})
                
                proxy_info = f"""
🌍 COUNTRY PROXY LIST CREATED!

✅ Successfully created proxy list for {country_name}

📍 LOCATION DETAILS:
• Country: {geo.get('country', country_name)}
• Region: {geo.get('region', 'N/A')}
• City: {geo.get('city', 'N/A')}
• ISP: {geo.get('isp', 'N/A')}

🔧 CONNECTION INFORMATION:
• Host: {data.get('login', 'N/A')}
• Port: {data.get('export', {}).get('ports', 'N/A')}
• Username: {data.get('login', 'N/A')}
• Password: {data.get('password', 'N/A')}

🔗 PROXY CONNECTION STRING:
{data.get('login', 'N/A')}:{data.get('password', 'N/A')}@{data.get('login', 'N/A')}:{data.get('export', {}).get('ports', 'N/A')}

🌐 DIRECT LINK:
http://{data.get('login', 'N/A')}:{data.get('password', 'N/A')}@{data.get('login', 'N/A')}:{data.get('export', {}).get('ports', 'N/A')}

📝 Whitelist: {data.get('whitelist', 'Not set')}
🔄 Rotation: {data.get('rotation', 'Default')}

💡 Usage Tip: You can use this proxy with any application that supports HTTP proxies.
                """
                return proxy_info
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                return f"❌ Error creating proxy list: {error_msg}"
                
        except Exception as e:
            logger.error(f"Create country list error: {e}")
            return f"❌ API Error: {str(e)}"

# Initialize proxy manager
proxy_mgr = ProxyManager(API_KEY)

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 Welcome Admin!\n\n"
            "🛠️ Admin Commands:\n"
            "/create - Create sub user\n"
            "/delete - Delete sub user\n"
            "/broadcast - Broadcast message\n\n"
            "👤 User Commands:\n"
            "/dashboard - Check usage\n"
            "/change_rotation - Change rotation timing\n"
            "/change_country - Change proxy country 🌍\n"
            "/support - Get assistance"
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to Proxy Manager Bot! 🤖\n\n"
            "📋 Available Commands:\n"
            "/dashboard - Check your usage 📊\n"
            "/change_rotation - Change rotation timing 🔄\n"
            "/change_country - Change proxy country 🌍\n"
            "/support - Get assistance 🆘\n\n"
            "💡 Simply use the commands to manage your proxies!"
        )

async def create_sub_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Administrator access required!")
        return ConversationHandler.END
    
    await update.message.reply_text("📝 Enter the amount of GB for the sub user:")
    return WAITING_GB

async def receive_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gb_amount = update.message.text.strip()
    
    if not gb_amount.isdigit() or int(gb_amount) <= 0:
        await update.message.reply_text("❌ Please enter a valid positive number!")
        return WAITING_GB
    
    await update.message.reply_text("⏳ Creating sub user...")
    result = proxy_mgr.create_sub_user(gb_amount)
    await update.message.reply_text(result)
    return ConversationHandler.END

async def delete_sub_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Administrator access required!")
        return ConversationHandler.END
    
    await update.message.reply_text("🗑️ Enter the Sub User ID to delete:")
    return WAITING_DELETE_ID

async def receive_delete_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    await update.message.reply_text("⏳ Deleting sub user...")
    result = proxy_mgr.delete_sub_user(package_key)
    await update.message.reply_text(result)
    return ConversationHandler.END

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Administrator access required!")
        return
    
    if context.args:
        message = " ".join(context.args)
        await update.message.reply_text(f"📢 Broadcast Message Sent:\n\n{message}")
    else:
        await update.message.reply_text("⚠️ Usage: /broadcast <your_message>")

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Please enter your Sub User ID:")
    return WAITING_SUB_USER_ID

async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    package_key = update.message.text.strip()
    await update.message.reply_text("⏳ Retrieving package information...")
    result = proxy_mgr.get_package_info(package_key)
    await update.message.reply_text(result)
    return ConversationHandler.END

async def change_rotation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Enter your Sub User ID:")
    return WAITING_ROTATION

async def ask_rotation_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for rotation value after receiving sub user ID"""
    package_key = update.message.text.strip()
    
    # Store package key in context for later use
    context.user_data['package_key'] = package_key
    
    # Explain rotation options
    message = """
🔄 ROTATION SETTINGS

Choose rotation timing:

-1 = Continuous rotation
 0 = Rotation per request
1-3600 = Rotation every X seconds

Examples:
• -1  → IP changes automatically
• 0   → New IP for each request  
• 60  → IP changes every 60 seconds
• 300 → IP changes every 5 minutes

📝 Enter rotation value (-1, 0, or 1-3600):
    """
    
    await update.message.reply_text(message)
    return WAITING_ROTATION + 1  # Next state

async def perform_rotation_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perform the rotation change after user provides rotation value"""
    rotation_value = update.message.text.strip()
    package_key = context.user_data.get('package_key')
    
    if not package_key:
        await update.message.reply_text("❌ Error: Sub User ID not found. Please start over.")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Changing rotation settings...")
    result = proxy_mgr.change_rotation(package_key, rotation_value)
    await update.message.reply_text(result)
    
    # Clean up
    if 'package_key' in context.user_data:
        del context.user_data['package_key']
    
    return ConversationHandler.END

async def change_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start country change process"""
    await update.message.reply_text("🌍 Please enter your Sub User ID:")
    return CHOOSING_COUNTRY

async def ask_country_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user to choose a country after receiving sub user ID"""
    package_key = update.message.text.strip()
    
    # Store package key in context for later use
    context.user_data['package_key'] = package_key
    
    # Get first page of countries
    reply_markup = proxy_mgr.get_country_keyboard(page=0)
    
    await update.message.reply_text(
        "🌍 **Choose Your Proxy Country**\n\n"
        "Browse through available countries using the navigation buttons below. "
        "Select your desired country to create a proxy list:",
        reply_markup=reply_markup
    )
    
    return CHOOSING_COUNTRY

async def handle_country_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle country selection from inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_country":
        await query.edit_message_text("❌ Country selection cancelled.")
        # Clean up
        if 'package_key' in context.user_data:
            del context.user_data['package_key']
        return ConversationHandler.END
    
    if query.data.startswith("page_"):
        # Handle pagination
        page = int(query.data.split("_")[1])
        reply_markup = proxy_mgr.get_country_keyboard(page=page)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return CHOOSING_COUNTRY
    
    if query.data.startswith("country_"):
        # Extract country code and name from callback data
        parts = query.data.split("_", 2)
        if len(parts) == 3:
            country_code = parts[1]
            country_name = parts[2]
            
            package_key = context.user_data.get('package_key')
            
            if not package_key:
                await query.edit_message_text("❌ Error: Sub User ID not found. Please start over.")
                return ConversationHandler.END
            
            await query.edit_message_text(f"⏳ Creating proxy list for **{country_name}**...")
            
            # Create proxy list for selected country
            result = proxy_mgr.create_country_list(package_key, country_code, country_name)
            await context.bot.send_message(chat_id=query.message.chat_id, text=result)
            
            # Clean up
            if 'package_key' in context.user_data:
                del context.user_data['package_key']
            
            return ConversationHandler.END
    
    return CHOOSING_COUNTRY

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_text = """
🆘 **Support Center**

Need help? Our support team is here for you!

📧 **Contact Support:**
👉 @professor_cry

🕒 **Availability:** 24/7

🔧 **We can help with:**
• Proxy setup issues
• Billing questions  
• Technical support
• Package upgrades
• Any other queries

Don't hesitate to reach out! We're happy to help. 😊
    """
    await update.message.reply_text(support_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation cancelled.")
    # Clean up any stored data
    if 'package_key' in context.user_data:
        del context.user_data['package_key']
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception occurred:", exc_info=context.error)
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ An error occurred. Please try again or contact support."
        )
    except:
        pass

def main():
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Conversation handlers
    create_conv = ConversationHandler(
        entry_points=[CommandHandler('create', create_sub_user)],
        states={
            WAITING_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gb)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    delete_conv = ConversationHandler(
        entry_points=[CommandHandler('delete', delete_sub_user)],
        states={
            WAITING_DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_id)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dashboard_conv = ConversationHandler(
        entry_points=[CommandHandler('dashboard', dashboard)],
        states={
            WAITING_SUB_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_dashboard)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Rotation conversation handler with two steps
    rotation_conv = ConversationHandler(
        entry_points=[CommandHandler('change_rotation', change_rotation)],
        states={
            WAITING_ROTATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_rotation_value)
            ],
            WAITING_ROTATION + 1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, perform_rotation_change)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Country change conversation handler
    country_conv = ConversationHandler(
        entry_points=[CommandHandler('change_country', change_country)],
        states={
            CHOOSING_COUNTRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_country_choice),
                CallbackQueryHandler(handle_country_selection)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    application.add_handler(create_conv)
    application.add_handler(delete_conv)
    application.add_handler(dashboard_conv)
    application.add_handler(rotation_conv)
    application.add_handler(country_conv)

    # Start bot with auto-restart capability
    print("🤖 Proxy Manager Bot is starting...")
    print(f"🔧 Admin ID: {ADMIN_ID}")
    print("🌍 Country feature: Worldwide countries ENABLED")
    print("🚀 Bot is ready and running!")
    
    while True:
        try:
            application.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            print(f"🔄 Restarting bot... Error: {e}")
            continue

if __name__ == '__main__':
    main()