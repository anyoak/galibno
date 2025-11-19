const { Telegraf, Markup } = require('telegraf');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');

// Bot configuration
const BOT_TOKEN = '8441847556:AAGO_XbbN_eJJrL944JCO6uzHW7TDjS5VEQ';
const ADMIN_ID = 6083895678;
const MIN_WITHDRAW = 100;
const MIN_DEPOSIT = 50;
const POINT_RATE = 0.10;

// Initialize bot
const bot = new Telegraf(BOT_TOKEN);

// Database setup
const db = new sqlite3.Database('bot_data.db');

// Initialize database tables
function initDatabase() {
    db.serialize(() => {
        // Users table
        db.run(`CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points REAL DEFAULT 0,
            deposit_balance REAL DEFAULT 0,
            wallet_address TEXT,
            is_banned BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )`);

        // Transactions table
        db.run(`CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            txid TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )`);

        // Withdrawal requests table
        db.run(`CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_number TEXT UNIQUE,
            user_id INTEGER,
            points REAL,
            usd_amount REAL,
            wallet_address TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )`);

        // Deposit invoices table
        db.run(`CREATE TABLE IF NOT EXISTS deposit_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            payment_url TEXT,
            admin_message_id INTEGER,
            user_message_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )`);
    });
    console.log('✅ Database initialized');
}

// Utility functions
function generateRequestNumber() {
    return Math.floor(1000 + Math.random() * 9000).toString();
}

function generateInvoiceNumber() {
    return Math.floor(100000 + Math.random() * 900000).toString();
}

// Database helper functions
function getUserData(userId) {
    return new Promise((resolve, reject) => {
        db.get('SELECT * FROM users WHERE user_id = ?', [userId], (err, row) => {
            if (err) reject(err);
            else if (row) resolve(row);
            else {
                // Create new user
                db.run('INSERT INTO users (user_id) VALUES (?)', [userId], function(err) {
                    if (err) reject(err);
                    else resolve({
                        user_id: userId,
                        points: 0,
                        deposit_balance: 0,
                        wallet_address: null,
                        is_banned: false
                    });
                });
            }
        });
    });
}

function updateUserPoints(userId, points) {
    return new Promise((resolve, reject) => {
        db.run('UPDATE users SET points = ? WHERE user_id = ?', [points, userId], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function updateDepositBalance(userId, amount) {
    return new Promise((resolve, reject) => {
        db.run('UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?', [amount, userId], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function addTransaction(userId, type, amount, txid = null, status = 'pending') {
    return new Promise((resolve, reject) => {
        db.run('INSERT INTO transactions (user_id, type, amount, txid, status) VALUES (?, ?, ?, ?, ?)',
            [userId, type, amount, txid, status], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function createWithdrawalRequest(userId, points, usdAmount, walletAddress) {
    return new Promise((resolve, reject) => {
        const requestNumber = generateRequestNumber();
        
        db.run(`INSERT INTO withdrawal_requests (request_number, user_id, points, usd_amount, wallet_address, status) 
                VALUES (?, ?, ?, ?, ?, 'pending')`,
            [requestNumber, userId, points, usdAmount, walletAddress], function(err) {
            if (err) reject(err);
            else {
                addTransaction(userId, 'withdraw', usdAmount, `REQ-${requestNumber}`, 'pending');
                resolve(requestNumber);
            }
        });
    });
}

function createDepositInvoice(userId, amount) {
    return new Promise((resolve, reject) => {
        const invoiceNumber = generateInvoiceNumber();
        
        db.run('INSERT INTO deposit_invoices (invoice_number, user_id, amount, status) VALUES (?, ?, ?, "pending")',
            [invoiceNumber, userId, amount], function(err) {
            if (err) reject(err);
            else resolve(invoiceNumber);
        });
    });
}

function updateInvoiceUrl(invoiceNumber, paymentUrl, adminMessageId, userMessageId) {
    return new Promise((resolve, reject) => {
        db.run(`UPDATE deposit_invoices 
                SET payment_url = ?, admin_message_id = ?, user_message_id = ?, status = 'waiting_payment' 
                WHERE invoice_number = ?`,
            [paymentUrl, adminMessageId, userMessageId, invoiceNumber], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function updateInvoiceStatus(invoiceNumber, status) {
    return new Promise((resolve, reject) => {
        db.run('UPDATE deposit_invoices SET status = ? WHERE invoice_number = ?', [status, invoiceNumber], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function getInvoiceByNumber(invoiceNumber) {
    return new Promise((resolve, reject) => {
        db.get(`SELECT di.*, u.points, u.deposit_balance 
                FROM deposit_invoices di 
                JOIN users u ON di.user_id = u.user_id 
                WHERE di.invoice_number = ?`, [invoiceNumber], (err, row) => {
            if (err) reject(err);
            else resolve(row);
        });
    });
}

function getPendingDepositInvoices() {
    return new Promise((resolve, reject) => {
        db.all(`SELECT di.*, u.points, u.deposit_balance 
                FROM deposit_invoices di 
                JOIN users u ON di.user_id = u.user_id 
                WHERE di.status IN ('pending', 'waiting_payment') 
                ORDER BY di.created_at DESC`, (err, rows) => {
            if (err) reject(err);
            else resolve(rows);
        });
    });
}

function getPendingWithdrawals() {
    return new Promise((resolve, reject) => {
        db.all(`SELECT wr.*, u.points as current_points, u.deposit_balance 
                FROM withdrawal_requests wr 
                JOIN users u ON wr.user_id = u.user_id 
                WHERE wr.status = 'pending' 
                ORDER BY wr.created_at DESC`, (err, rows) => {
            if (err) reject(err);
            else resolve(rows);
        });
    });
}

function getWithdrawalByRequestNumber(requestNumber) {
    return new Promise((resolve, reject) => {
        db.get(`SELECT wr.*, u.points as current_points, u.deposit_balance 
                FROM withdrawal_requests wr 
                JOIN users u ON wr.user_id = u.user_id 
                WHERE wr.request_number = ?`, [requestNumber], (err, row) => {
            if (err) reject(err);
            else resolve(row);
        });
    });
}

function updateWithdrawalStatus(requestNumber, status) {
    return new Promise((resolve, reject) => {
        db.run('UPDATE withdrawal_requests SET status = ? WHERE request_number = ?', [status, requestNumber], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function updateTransactionStatus(txid, status) {
    return new Promise((resolve, reject) => {
        db.run('UPDATE transactions SET status = ? WHERE txid = ?', [status, txid], (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

function hasPendingWithdrawal(userId) {
    return new Promise((resolve, reject) => {
        db.get('SELECT id FROM withdrawal_requests WHERE user_id = ? AND status = "pending"', [userId], (err, row) => {
            if (err) reject(err);
            else resolve(!!row);
        });
    });
}

function hasPendingDeposit(userId) {
    return new Promise((resolve, reject) => {
        db.get('SELECT id FROM deposit_invoices WHERE user_id = ? AND status IN ("pending", "waiting_payment")', [userId], (err, row) => {
            if (err) reject(err);
            else resolve(!!row);
        });
    });
}

// User commands
bot.start(async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.reply('❌ You are banned from using this bot.');
    }
    
    const keyboard = Markup.inlineKeyboard([
        [Markup.button.callback(`💰 ${userData.points.toFixed(2)} PTS`, 'points_display')],
        [
            Markup.button.callback('Deposit', 'deposit'),
            Markup.button.callback('Withdraw', 'withdraw')
        ]
    ]);
    
    const welcomeText = `🤖 **Welcome to Crypto Bot!**

💎 **1 Point = $${POINT_RATE}**
💸 **Min Withdraw:** ${MIN_WITHDRAW} points
💰 **Min Deposit:** $${MIN_DEPOSIT} USDT

Use /setwallet to set your SOL wallet for withdrawals`;
    
    await ctx.reply(welcomeText, { 
        parse_mode: 'Markdown', 
        ...keyboard 
    });
});

// Set wallet command
bot.command('setwallet', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.reply('❌ You are banned from using this bot.');
    }
    
    const walletAddress = ctx.message.text.split(' ').slice(1).join(' ');
    if (!walletAddress) {
        return ctx.reply('Usage: /setwallet YOUR_SOL_WALLET_ADDRESS');
    }
    
    return new Promise((resolve, reject) => {
        db.run('UPDATE users SET wallet_address = ? WHERE user_id = ?', [walletAddress, userId], async (err) => {
            if (err) {
                await ctx.reply('❌ Error setting wallet address.');
                reject(err);
            } else {
                await ctx.reply(`✅ **SOL Wallet Set!**\n\n\`${walletAddress}\``, { parse_mode: 'Markdown' });
                resolve();
            }
        });
    });
});

// Balance command
bot.command('balance', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.reply('❌ You are banned from using this bot.');
    }
    
    const pendingWithdrawal = await hasPendingWithdrawal(userId);
    const pendingDeposit = await hasPendingDeposit(userId);
    
    const status = pendingDeposit ? '⏳ Pending deposit' : 
                  pendingWithdrawal ? '⏳ Pending withdrawal' : '✅ Active';
    
    const balanceText = `💰 **YOUR BALANCE**

💎 **Points:** ${userData.points.toFixed(2)} PTS
💵 **Value:** $${(userData.points * POINT_RATE).toFixed(2)}
📥 **Deposited:** $${userData.deposit_balance.toFixed(2)}
📊 **Status:** ${status}
💳 **Wallet:** ${userData.wallet_address || 'Not set'}`;
    
    await ctx.reply(balanceText, { parse_mode: 'Markdown' });
});

// History command
bot.command('history', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.reply('❌ You are banned from using this bot.');
    }
    
    return new Promise((resolve, reject) => {
        db.all(`SELECT type, amount, txid, status, created_at 
                FROM transactions 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 10`, [userId], async (err, transactions) => {
            if (err) {
                await ctx.reply('❌ Error fetching history.');
                reject(err);
                return;
            }
            
            if (!transactions.length) {
                await ctx.reply('📊 No transactions found');
                resolve();
                return;
            }
            
            let historyText = '📊 **TRANSACTION HISTORY**\n\n';
            
            transactions.forEach(trans => {
                const emoji = trans.type === 'deposit' ? '📥' : '📤';
                const statusEmoji = trans.status === 'approved' ? '✅' : 
                                  trans.status === 'rejected' ? '❌' : '⏳';
                
                historyText += `${emoji} **${trans.type.toUpperCase()}:** $${trans.amount.toFixed(2)}\n`;
                historyText += `**Status:** ${statusEmoji} ${trans.status.toUpperCase()}\n`;
                
                if (trans.txid) {
                    if (trans.txid.startsWith('REQ-')) {
                        historyText += `**Request:** #${trans.txid.replace('REQ-', '')}\n`;
                    } else if (trans.txid.startsWith('INV-')) {
                        historyText += `**Invoice:** #${trans.txid.replace('INV-', '')}\n`;
                    }
                }
                
                historyText += `**Date:** ${trans.created_at}\n`;
                historyText += '─'.repeat(20) + '\n';
            });
            
            await ctx.reply(historyText, { parse_mode: 'Markdown' });
            resolve();
        });
    });
});

// Cancel command
bot.command('cancel', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.reply('❌ You are banned from using this bot.');
    }
    
    const cancelText = `To cancel your investment and for any other inquiries, please contact @Symbioticl directly.

We're here to help you!`;
    
    await ctx.reply(cancelText);
});

// Button handlers
bot.action('points_display', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.editMessageText('❌ You are banned from using this bot.');
    }
    
    const keyboard = Markup.inlineKeyboard([
        [Markup.button.callback(`💰 ${userData.points.toFixed(2)} PTS`, 'points_display')],
        [
            Markup.button.callback('Deposit', 'deposit'),
            Markup.button.callback('Withdraw', 'withdraw')
        ]
    ]);
    
    await ctx.editMessageReplyMarkup(keyboard.reply_markup);
});

bot.action('deposit', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.editMessageText('❌ You are banned from using this bot.');
    }
    
    if (await hasPendingDeposit(userId)) {
        return ctx.editMessageText('⏳ You already have a pending deposit request. Please wait for it to be processed before making a new deposit.');
    }
    
    await ctx.editMessageText(`💵 **Enter Deposit Amount**

Minimum: $${MIN_DEPOSIT} USDT

Send the amount as a message:
**Example:** \`50\` or \`100\``, { parse_mode: 'Markdown' });
    
    // Store state for this user
    ctx.session = ctx.session || {};
    ctx.session.waitingForDepositAmount = true;
});

bot.action('withdraw', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.editMessageText('❌ You are banned from using this bot.');
    }
    
    if (await hasPendingWithdrawal(userId)) {
        return ctx.editMessageText('⏳ You already have a pending withdrawal request. Please wait for it to be processed before making a new request.');
    }
    
    if (userData.points < MIN_WITHDRAW) {
        return ctx.editMessageText(`❌ **Minimum withdrawal is ${MIN_WITHDRAW} points.**\nYour current points: ${userData.points.toFixed(2)}`);
    }
    
    if (!userData.wallet_address) {
        return ctx.editMessageText('❌ Please set your SOL wallet first using /setwallet');
    }
    
    const usdAmount = userData.points * POINT_RATE;
    const requestNumber = await createWithdrawalRequest(userId, userData.points, usdAmount, userData.wallet_address);
    
    // Notify admin
    const adminMessage = `🔄 **NEW WITHDRAWAL REQUEST** #${requestNumber}

👤 **User:** ${userId} (@${ctx.from.username || 'N/A'})
💰 **Amount:** $${usdAmount.toFixed(2)}
💎 **Points:** ${userData.points.toFixed(2)} PTS
💳 **Wallet:** \`${userData.wallet_address}\`

Use: \`/approve ${requestNumber}\` to approve
Use: \`/reject ${requestNumber}\` to reject`;
    
    try {
        await bot.telegram.sendMessage(ADMIN_ID, adminMessage, { parse_mode: 'Markdown' });
    } catch (error) {
        console.error('Admin notification failed:', error);
    }
    
    await ctx.editMessageText(`✅ **Withdrawal Request Submitted!**

📋 **Request ID:** #${requestNumber}
💰 **Amount:** $${usdAmount.toFixed(2)}
💎 **Points:** ${userData.points.toFixed(2)} PTS

⏳ Waiting for admin approval...`);
});

// Handle deposit amount input
bot.on('text', async (ctx) => {
    const userId = ctx.from.id;
    const userData = await getUserData(userId);
    
    if (userData.is_banned) {
        return ctx.reply('❌ You are banned from using this bot.');
    }
    
    // Check if waiting for deposit amount
    if (ctx.session && ctx.session.waitingForDepositAmount) {
        const amountText = ctx.message.text;
        const amount = parseFloat(amountText);
        
        if (isNaN(amount) || amount < MIN_DEPOSIT) {
            return ctx.reply(`❌ Please enter a valid number (minimum $${MIN_DEPOSIT})`);
        }
        
        // Clear the state
        ctx.session.waitingForDepositAmount = false;
        
        const creatingMsg = await ctx.reply(`🔄 Creating invoice for $${amount.toFixed(2)}...`);
        
        try {
            const invoiceNumber = await createDepositInvoice(userId, amount);
            
            // Send to admin
            const adminKeyboard = Markup.inlineKeyboard([
                [Markup.button.callback('📤 Send Payment URL', `send_url_${invoiceNumber}`)]
            ]);
            
            const adminMessage = `💰 **NEW DEPOSIT INVOICE** #${invoiceNumber}

👤 **User:** ${userId} (@${ctx.from.username || 'N/A'})
💵 **Amount:** $${amount.toFixed(2)}
💎 **Points to add:** ${(amount / POINT_RATE).toFixed(2)} PTS

**Click below to send payment URL:**`;
            
            const adminMsg = await bot.telegram.sendMessage(ADMIN_ID, adminMessage, {
                parse_mode: 'Markdown',
                ...adminKeyboard
            });
            
            // Store admin message ID
            await updateInvoiceUrl(invoiceNumber, '', adminMsg.message_id, creatingMsg.message_id);
            
            await ctx.telegram.editMessageText(
                ctx.chat.id,
                creatingMsg.message_id,
                null,
                `✅ **Invoice Created!**

📋 **Invoice Number:** #${invoiceNumber}
💰 **Amount:** $${amount.toFixed(2)}
💎 **Points:** ${(amount / POINT_RATE).toFixed(2)} PTS

⏳ Admin will send payment URL shortly...`,
                { parse_mode: 'Markdown' }
            );
            
        } catch (error) {
            console.error('Invoice creation failed:', error);
            await ctx.reply('❌ Failed to create invoice. Please try again.');
        }
    }
});

// Admin send URL callback
bot.action(/send_url_(.+)/, async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.answerCbQuery('❌ Access denied.');
    }
    
    const invoiceNumber = ctx.match[1];
    const invoice = await getInvoiceByNumber(invoiceNumber);
    
    if (!invoice) {
        return ctx.editMessageText('❌ Invoice not found.');
    }
    
    await ctx.editMessageText(`📤 **Send Payment URL**

📋 **Invoice:** #${invoiceNumber}
👤 **User:** ${invoice.user_id}
💵 **Amount:** $${invoice.amount.toFixed(2)}

**Please reply with the payment URL:**`);
    
    // Store state for admin
    ctx.session = ctx.session || {};
    ctx.session.waitingUrlFor = invoiceNumber;
});

// Handle admin URL input
bot.on('text', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    
    if (ctx.session && ctx.session.waitingUrlFor) {
        const invoiceNumber = ctx.session.waitingUrlFor;
        const paymentUrl = ctx.message.text.trim();
        
        // Clear the state
        ctx.session.waitingUrlFor = null;
        
        if (!paymentUrl.startsWith('http://') && !paymentUrl.startsWith('https://')) {
            return ctx.reply('❌ Please provide a valid URL starting with http:// or https://');
        }
        
        const invoice = await getInvoiceByNumber(invoiceNumber);
        if (!invoice) {
            return ctx.reply('❌ Invoice not found.');
        }
        
        // Send URL to user
        const userKeyboard = Markup.inlineKeyboard([
            [Markup.button.url('📥 Pay Now', paymentUrl)],
            [Markup.button.callback('✅ I\'ve Completed Payment', `confirm_payment_${invoiceNumber}`)]
        ]);
        
        const userMessage = `🔄 **Please Complete Deposit**

📋 **Invoice:** #${invoiceNumber}
💵 **Amount:** $${invoice.amount.toFixed(2)}
💎 **Points:** ${(invoice.amount / POINT_RATE).toFixed(2)} PTS

**Click the button below to make payment:**`;
        
        try {
            const userMsg = await bot.telegram.sendMessage(invoice.user_id, userMessage, {
                ...userKeyboard
            });
            
            await updateInvoiceUrl(invoiceNumber, paymentUrl, ctx.message.message_id, userMsg.message_id);
            
            await ctx.reply(`✅ **Payment URL Sent!**

📋 **Invoice:** #${invoiceNumber}
👤 **User:** ${invoice.user_id}
✅ User notified successfully`);
            
        } catch (error) {
            console.error('User message failed:', error);
            await ctx.reply('❌ Failed to send URL to user. User may have blocked the bot.');
        }
    }
});

// Payment confirmation
bot.action(/confirm_payment_(.+)/, async (ctx) => {
    const invoiceNumber = ctx.match[1];
    const invoice = await getInvoiceByNumber(invoiceNumber);
    
    if (!invoice || invoice.user_id !== ctx.from.id) {
        return ctx.answerCbQuery('❌ Invoice not found.');
    }
    
    await updateInvoiceStatus(invoiceNumber, 'paid');
    
    const adminKeyboard = Markup.inlineKeyboard([
        [
            Markup.button.callback('✅ Approve Deposit', `admin_approve_${invoiceNumber}`),
            Markup.button.callback('❌ Reject Deposit', `admin_reject_${invoiceNumber}`)
        ]
    ]);
    
    const adminMessage = `💰 **PAYMENT CONFIRMED** #${invoiceNumber}

👤 **User:** ${ctx.from.id} (@${ctx.from.username || 'N/A'})
💵 **Amount:** $${invoice.amount.toFixed(2)}
💎 **Points to add:** ${(invoice.amount / POINT_RATE).toFixed(2)} PTS

**Approve this deposit?**`;
    
    try {
        const adminMsg = await bot.telegram.sendMessage(ADMIN_ID, adminMessage, {
            ...adminKeyboard
        });
        
        await updateInvoiceUrl(invoiceNumber, invoice.payment_url, adminMsg.message_id, invoice.user_message_id);
    } catch (error) {
        console.error('Admin message failed:', error);
    }
    
    await ctx.editMessageText(`✅ **Payment Confirmed!**

📋 **Invoice:** #${invoiceNumber}
💰 **Amount:** $${invoice.amount.toFixed(2)}

⏳ Waiting for admin approval...

If admin doesn't respond within 1 hour, please contact support.`);
});

// Admin approve deposit
bot.action(/admin_approve_(.+)/, async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.answerCbQuery('❌ Access denied.');
    }
    
    const invoiceNumber = ctx.match[1];
    const invoice = await getInvoiceByNumber(invoiceNumber);
    
    if (!invoice) {
        return ctx.editMessageText('❌ Invoice not found.');
    }
    
    await updateInvoiceStatus(invoiceNumber, 'approved');
    const amount = invoice.amount;
    const pointsToAdd = amount / POINT_RATE;
    const userId = invoice.user_id;
    
    await updateDepositBalance(userId, amount);
    const userData = await getUserData(userId);
    const newPoints = userData.points + pointsToAdd;
    await updateUserPoints(userId, newPoints);
    
    await addTransaction(userId, 'deposit', amount, `INV-${invoiceNumber}`, 'approved');
    
    try {
        const userMessage = `✅ **Deposit Approved!**

📋 **Invoice:** #${invoiceNumber}
💰 **Amount:** $${amount.toFixed(2)}
💎 **Points Added:** ${pointsToAdd.toFixed(2)} PTS
💳 **New Balance:** ${newPoints.toFixed(2)} PTS

Thank you for your deposit! 🎉`;
        
        await bot.telegram.sendMessage(userId, userMessage);
    } catch (error) {
        console.error('User notification failed:', error);
    }
    
    await ctx.editMessageText(`✅ Deposit #${invoiceNumber} approved! User balance updated.`);
});

// Admin reject deposit
bot.action(/admin_reject_(.+)/, async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.answerCbQuery('❌ Access denied.');
    }
    
    const invoiceNumber = ctx.match[1];
    const invoice = await getInvoiceByNumber(invoiceNumber);
    
    if (!invoice) {
        return ctx.editMessageText('❌ Invoice not found.');
    }
    
    await updateInvoiceStatus(invoiceNumber, 'rejected');
    const userId = invoice.user_id;
    
    try {
        const userMessage = `❌ **Deposit Rejected**

📋 **Invoice:** #${invoiceNumber}
💰 **Amount:** $${invoice.amount.toFixed(2)}

Your deposit request has been rejected.
Please contact admin for more information.`;
        
        await bot.telegram.sendMessage(userId, userMessage);
    } catch (error) {
        console.error('User notification failed:', error);
    }
    
    await ctx.editMessageText(`❌ Deposit #${invoiceNumber} rejected. User notified.`);
});

// Admin commands
bot.command('admin', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    const commands = `👑 **ADMIN PANEL COMMANDS**

📊 **Statistics:**
/stats - Bot statistics

📥 **Deposit Management:**
/deposits - Pending deposits

💸 **Withdrawal Management:**
/withdrawals - Pending withdrawals
/approve <request_id> - Approve withdrawal
/reject <request_id> - Reject withdrawal

👥 **User Management:**
/users - All users
/ban <user_id> - Ban user
/unban <user_id> - Unban user
/setpoints <user_id> <points> - Set user points

📢 **Broadcast:**
/broadcast <message> - Broadcast to all users`;
    
    await ctx.reply(commands, { parse_mode: 'Markdown' });
});

bot.command('stats', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    return new Promise((resolve, reject) => {
        db.get('SELECT COUNT(*) as user_count, SUM(points) as total_points, SUM(deposit_balance) as total_deposit FROM users', async (err, userStats) => {
            if (err) {
                await ctx.reply('❌ Error fetching statistics.');
                reject(err);
                return;
            }
            
            db.get('SELECT COUNT(*) as pending_deposits FROM deposit_invoices WHERE status IN ("pending", "waiting_payment")', async (err, depositStats) => {
                if (err) {
                    await ctx.reply('❌ Error fetching statistics.');
                    reject(err);
                    return;
                }
                
                db.get('SELECT COUNT(*) as pending_withdrawals FROM withdrawal_requests WHERE status = "pending"', async (err, withdrawalStats) => {
                    if (err) {
                        await ctx.reply('❌ Error fetching statistics.');
                        reject(err);
                        return;
                    }
                    
                    const statsText = `📊 **BOT STATISTICS**

👥 **Total Users:** ${userStats.user_count}
💎 **Total Points:** ${(userStats.total_points || 0).toFixed(2)}
💰 **Total Deposit:** $${(userStats.total_deposit || 0).toFixed(2)}
📥 **Pending Deposits:** ${depositStats.pending_deposits}
📤 **Pending Withdrawals:** ${withdrawalStats.pending_withdrawals}
💵 **Total Value:** $${((userStats.total_points || 0) * POINT_RATE).toFixed(2)}`;
                    
                    await ctx.reply(statsText, { parse_mode: 'Markdown' });
                    resolve();
                });
            });
        });
    });
});

bot.command('deposits', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    try {
        const invoices = await getPendingDepositInvoices();
        
        if (!invoices.length) {
            return ctx.reply('✅ No pending deposits');
        }
        
        for (const invoice of invoices) {
            const statusText = invoice.status === 'pending' ? '🟡 Waiting URL' : '🟠 Waiting Payment';
            
            const message = `💰 **INVOICE** #${invoice.invoice_number}
👤 **User:** ${invoice.user_id}
💵 **Amount:** $${invoice.amount.toFixed(2)}
📊 **Status:** ${statusText}
📅 **Created:** ${invoice.created_at}
💎 **User Points:** ${invoice.points.toFixed(2)} PTS`;
            
            const keyboard = Markup.inlineKeyboard([
                [Markup.button.callback('📤 Send URL', `send_url_${invoice.invoice_number}`)]
            ]);
            
            await ctx.reply(message, { 
                parse_mode: 'Markdown',
                ...keyboard
            });
        }
    } catch (error) {
        console.error('Error fetching deposits:', error);
        await ctx.reply('❌ Error fetching pending deposits.');
    }
});

bot.command('withdrawals', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    try {
        const withdrawals = await getPendingWithdrawals();
        
        if (!withdrawals.length) {
            return ctx.reply('✅ No pending withdrawals');
        }
        
        for (const withdrawal of withdrawals) {
            const message = `💸 **WITHDRAWAL** #${withdrawal.request_number}
👤 **User:** ${withdrawal.user_id}
💵 **Amount:** $${withdrawal.usd_amount.toFixed(2)}
💎 **Points:** ${withdrawal.points.toFixed(2)} PTS
💳 **Wallet:** ${withdrawal.wallet_address}
📅 **Created:** ${withdrawal.created_at}`;
            
            await ctx.reply(message, { parse_mode: 'Markdown' });
        }
    } catch (error) {
        console.error('Error fetching withdrawals:', error);
        await ctx.reply('❌ Error fetching pending withdrawals.');
    }
});

bot.command('approve', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    const args = ctx.message.text.split(' ').slice(1);
    if (args.length < 1) {
        return ctx.reply('Usage: /approve REQUEST_NUMBER');
    }
    
    const requestNumber = args[0];
    
    try {
        const withdrawal = await getWithdrawalByRequestNumber(requestNumber);
        
        if (!withdrawal) {
            return ctx.reply('❌ Withdrawal not found');
        }
        
        await updateWithdrawalStatus(requestNumber, 'approved');
        await updateTransactionStatus(`REQ-${requestNumber}`, 'approved');
        
        const userData = await getUserData(withdrawal.user_id);
        const newPoints = userData.points - withdrawal.points;
        await updateUserPoints(withdrawal.user_id, newPoints);
        
        try {
            const userMessage = `✅ **Withdrawal Approved!**

📋 **Request:** #${requestNumber}
💵 **Amount:** $${withdrawal.usd_amount.toFixed(2)}
💎 **New Balance:** ${newPoints.toFixed(2)} PTS

Funds will be sent to your wallet shortly.`;
            
            await bot.telegram.sendMessage(withdrawal.user_id, userMessage);
        } catch (error) {
            console.error('User notification failed:', error);
        }
        
        await ctx.reply(`✅ Withdrawal #${requestNumber} approved! User balance updated.`);
    } catch (error) {
        console.error('Error approving withdrawal:', error);
        await ctx.reply('❌ Error approving withdrawal.');
    }
});

bot.command('reject', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    const args = ctx.message.text.split(' ').slice(1);
    if (args.length < 1) {
        return ctx.reply('Usage: /reject REQUEST_NUMBER');
    }
    
    const requestNumber = args[0];
    
    try {
        const withdrawal = await getWithdrawalByRequestNumber(requestNumber);
        
        if (!withdrawal) {
            return ctx.reply('❌ Withdrawal not found');
        }
        
        await updateWithdrawalStatus(requestNumber, 'rejected');
        await updateTransactionStatus(`REQ-${requestNumber}`, 'rejected');
        
        try {
            const userMessage = `❌ Withdrawal #${requestNumber} rejected. Contact admin.`;
            await bot.telegram.sendMessage(withdrawal.user_id, userMessage);
        } catch (error) {
            console.error('User notification failed:', error);
        }
        
        await ctx.reply(`❌ Withdrawal #${requestNumber} rejected. User notified.`);
    } catch (error) {
        console.error('Error rejecting withdrawal:', error);
        await ctx.reply('❌ Error rejecting withdrawal.');
    }
});

bot.command('users', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) {
        return ctx.reply('❌ Access denied.');
    }
    
    return new Promise((resolve, reject) => {
        db.all('SELECT user_id, points, deposit_balance, is_banned FROM users ORDER BY points DESC LIMIT 50', async (err, users) => {
            if (err) {
                await ctx.reply('❌ Error fetching users.');
                reject(err);
                return;
            }
            
            if (!users.length) {
                await ctx.reply('❌ No users found');
                resolve();
                return;
            }
            
            let usersText = '👥 **ALL USERS** (Top 50 by points)\n\n';
            
            users.forEach(user => {
                const status = user.is_banned ? '❌ BANNED' : '✅ ACTIVE';
                usersText += `👤 **User:** ${user.user_id}\n`;
                usersText += `💎 **Points:** ${user.points.toFixed(2)}\n`;
                usersText += `💰 **Deposit:** $${user.deposit_balance.toFixed(2)}\n`;
                usersText += `📊 **Status:** ${status}\n`;
                usersText += '─'.repeat(20) + '\n';
            });
            
            await ctx.reply(usersText, { parse_mode: 'Markdown' });
            resolve();
        });
    });
});

// Error handling
bot.catch((err, ctx) => {
    console.error(`Error for ${ctx.updateType}:`, err);
});

// Start bot
async function startBot() {
    try {
        initDatabase();
        await bot.launch();
        console.log('🤖 Bot started successfully');
        console.log('✅ All systems operational');
    } catch (error) {
        console.error('Failed to start bot:', error);
        process.exit(1);
    }
}

// Graceful shutdown
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));

// Start the bot
startBot();
