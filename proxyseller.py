import requests
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

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
WAITING_GB, WAITING_DELETE_ID, WAITING_SUB_USER_ID, WAITING_COUNTRY_CHANGE = range(4)

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
    
    def change_country(self, package_key, country_code):
        """Change country/rotation for sub user"""
        try:
            url = f"{self.base_url}/{self.api_key}/residentsubuser/list/rotation"
            
            # Clean the country code
            country_code = country_code.upper().strip()
            
            # For Proxy Seller API, we use rotation parameter
            # The API will automatically assign a proxy from the selected country
            data = {
                "package_key": package_key, 
                "rotation": 60  # 60 seconds rotation
            }
            
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            logger.info(f"Change country response: {result}")
            
            if result.get('status') == 'success':
                data = result['data']
                geo = data.get('geo', {})
                
                proxy_info = f"""
🔄 REGION CHANGED SUCCESSFULLY!

🌍 LOCATION:
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

⚙️ Rotation: {data.get('rotation', 'N/A')}
                """
                return proxy_info
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                return f"❌ Error: {error_msg}"
                
        except Exception as e:
            logger.error(f"Change country error: {e}")
            return f"❌ API Error: {str(e)}"

# Initialize proxy manager
proxy_mgr = ProxyManager(API_KEY)

# Available countries - you can expand this list
AVAILABLE_COUNTRIES = {
    'US': 'United States',
    'UK': 'United Kingdom', 
    'GB': 'United Kingdom',
    'DE': 'Germany',
    'FR': 'France',
    'CA': 'Canada',
    'NL': 'Netherlands',
    'SG': 'Singapore',
    'JP': 'Japan',
    'AU': 'Australia',
    'BR': 'Brazil',
    'IN': 'India',
    'RU': 'Russia',
    'CH': 'Switzerland',
    'SE': 'Sweden',
    'NO': 'Norway',
    'DK': 'Denmark',
    'FI': 'Finland',
    'PL': 'Poland',
    'IT': 'Italy',
    'ES': 'Spain',
    'PT': 'Portugal',
    'BE': 'Belgium',
    'AT': 'Austria',
    'IE': 'Ireland',
    'NZ': 'New Zealand',
    'KR': 'South Korea',
    'HK': 'Hong Kong',
    'TW': 'Taiwan',
    'TR': 'Turkey',
    'UA': 'Ukraine'
}

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
            "/change_country - Change region/rotation\n"
            "/support - Get assistance"
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to Proxy Manager!\n\n"
            "Available Commands:\n"
            "/dashboard - Check your usage\n"
            "/change_country - Change region/rotation\n"
            "/support - Get assistance"
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

async def change_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 Enter your Sub User ID:")
    return WAITING_COUNTRY_CHANGE

async def ask_country_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for country code after receiving sub user ID"""
    package_key = update.message.text.strip()
    
    # Store package key in context for later use
    context.user_data['package_key'] = package_key
    
    # Ask for country code directly
    message = """
🌍 COUNTRY SELECTION

Available countries (use 2-letter codes):

US  - United States
UK  - United Kingdom  
DE  - Germany
FR  - France
CA  - Canada
NL  - Netherlands
SG  - Singapore
JP  - Japan
AU  - Australia
BR  - Brazil
IN  - India
and more...

📝 Please enter the country code (e.g., US, UK, DE):
    """
    
    await update.message.reply_text(message)
    return WAITING_COUNTRY_CHANGE + 1  # Next state

async def perform_country_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perform the country change after user provides country code"""
    country_code = update.message.text.strip().upper()
    package_key = context.user_data.get('package_key')
    
    if not package_key:
        await update.message.reply_text("❌ Error: Sub User ID not found. Please start over.")
        return ConversationHandler.END
    
    # Validate country code
    if country_code not in AVAILABLE_COUNTRIES:
        await update.message.reply_text(f"❌ Invalid country code: {country_code}\n\nPlease enter a valid 2-letter country code (e.g., US, UK, DE)")
        return WAITING_COUNTRY_CHANGE + 1
    
    country_name = AVAILABLE_COUNTRIES[country_code]
    
    await update.message.reply_text(f"⏳ Changing region to {country_name} ({country_code})...")
    result = proxy_mgr.change_country(package_key, country_code)
    await update.message.reply_text(result)
    
    # Clean up
    if 'package_key' in context.user_data:
        del context.user_data['package_key']
    
    return ConversationHandler.END

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_text = """
🆘 Support Center

For purchasing super-proxy packages or any other assistance, please contact:
👉 @professor_cry

Our support team is available 24/7 to help you!
    """
    await update.message.reply_text(support_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception occurred:", exc_info=context.error)

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

    # Updated country conversation handler with two steps
    country_conv = ConversationHandler(
        entry_points=[CommandHandler('change_country', change_country)],
        states={
            WAITING_COUNTRY_CHANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_country_code)
            ],
            WAITING_COUNTRY_CHANGE + 1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, perform_country_change)
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
    application.add_handler(country_conv)

    # Start bot with auto-restart capability
    print("🤖 Proxy Manager Bot is starting...")
    print(f"🔧 Admin ID: {ADMIN_ID}")
    print(f"🌐 Available Countries: {len(AVAILABLE_COUNTRIES)} countries")
    
    while True:
        try:
            application.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            print(f"🔄 Restarting bot... Error: {e}")
            continue

if __name__ == '__main__':
    main()
