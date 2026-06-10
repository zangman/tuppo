const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');
const express = require('express');
const axios = require('axios');
const yaml = require('js-yaml');

const app = express();
app.use(express.json());
const PORT = 3000;

// Configuration
const DB_PATH = path.join(__dirname, '../whatsapp.db');
const AGENT_WEBHOOK_URL = 'http://localhost:5000/webhook';
const CONFIG_PATH = path.join(__dirname, '../config.yaml');

function loadConfig() {
    try {
        return yaml.load(fs.readFileSync(CONFIG_PATH, 'utf8'));
    } catch (e) {
        return { owner: {}, whatsapp: { autoresponder: {} } };
    }
}

// Load owner WhatsApp ID for mention detection
let ownerWhatsAppId = null;
try {
    const cfg = loadConfig();
    ownerWhatsAppId = cfg.owner?.whatsapp_id;
} catch (e) {
    console.warn('Could not load owner_whatsapp_id from config:', e.message);
}

// API Endpoints
app.post('/send-message', async (req, res) => {
    const { chatId, text, mark_unread } = req.body;
    if (!chatId || !text) {
        return res.status(400).json({ error: 'Missing chatId or text' });
    }
    try {
        await client.sendMessage(chatId, text);

        // Mark chat as unread only when explicitly requested (autoresponder responses)
        if (mark_unread) {
            try {
                const chat = await client.getChatById(chatId);
                if (chat && !chat.isGroup) {
                    await chat.markUnread();
                }
            } catch (e) {
                console.error(`Error marking chat as unread: ${e.message}`);
            }
        }

        res.json({ success: true, message: 'Message sent successfully' });
    } catch (e) {
        console.error('Error sending message:', e);
        res.status(500).json({ error: 'Failed to send message', details: e.message });
    }
});

app.post('/take-message', (req, res) => {
    const { sender_name, sender_id, chat_name, chat_id, message_text } = req.body;
    if (!sender_name || !message_text) {
        return res.status(400).json({ error: 'Missing sender_name or message_text' });
    }
    // Look up display name from contacts table
    const cleanId = sender_id.replace('@c.us', '').replace('@lid', '');
    db.get("SELECT display_name FROM contacts WHERE chat_id = ? OR chat_id = ?", [sender_id, cleanId], (err, row) => {
        const displayName = row ? row.display_name : sender_name;
        const stmt = db.prepare(`INSERT INTO messages_for_owner (sender_name, sender_id, chat_name, chat_id, message_text)
            VALUES (?, ?, ?, ?, ?)`);
        stmt.run(displayName, sender_id, chat_name || 'Private Chat', chat_id, message_text, function(err) {
            if (err) {
                console.error('Error inserting message for owner:', err.message);
                res.status(500).json({ error: 'Failed to save message', details: err.message });
            } else {
                console.log(`Saved message for owner from ${displayName}: ${message_text.substring(0, 50)}...`);
                res.json({ success: true, id: this.lastID });
            }
        });
        stmt.finalize();
    });
});

app.listen(PORT, () => {
    console.log(`WhatsApp API Server listening on port ${PORT}`);
});

// Initialize Database
const db = new sqlite3.Database(DB_PATH, (err) => {
    if (err) {
        console.error('Error opening database:', err.message);
    } else {
        console.log('Connected to the SQLite database.');
        db.serialize(() => {
            db.run(`CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                group_id TEXT,
                group_name TEXT,
                sender TEXT,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )`, (err) => {
                if (err) console.error('Error creating messages table:', err.message);
            });

            db.run(`CREATE TABLE IF NOT EXISTS chat_status (
                chat_id TEXT PRIMARY KEY,
                last_read_timestamp DATETIME
            )`, (err) => {
                if (err) console.error('Error creating chat_status table:', err.message);
            });

            db.run(`CREATE TABLE IF NOT EXISTS contacts (
                chat_id TEXT PRIMARY KEY,
                display_name TEXT,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )`, (err) => {
                if (err) console.error('Error creating contacts table:', err.message);
            });

            db.run(`CREATE TABLE IF NOT EXISTS whatsapp_proposals (
                proposal_id TEXT PRIMARY KEY,
                chat_id TEXT,
                recipient_name TEXT,
                message_text TEXT,
                status TEXT DEFAULT 'pending'
            )`, (err) => {
                if (err) console.error('Error creating whatsapp_proposals table:', err.message);
            });

            db.run(`CREATE TABLE IF NOT EXISTS messages_for_owner (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT,
                sender_id TEXT,
                chat_name TEXT,
                chat_id TEXT,
                message_text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                read_status TEXT DEFAULT 'unread'
            )`, (err) => {
                if (err) console.error('Error creating messages_for_owner table:', err.message);
            });
        });
    }
});

// Initialize WhatsApp Client
// We use LocalAuth to persist the session so you don't have to scan the QR every time
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

// Generate QR Code for authentication
client.on('qr', (qr) => {
    console.log('Scan the QR code below with your WhatsApp app:');
    qrcode.generate(qr, { small: true });
});

// Client ready
client.on('ready', () => {
    console.log('WhatsApp Client is ready and authenticated!');
});

// Message Listener
client.on('message_create', async (msg) => {
    try {
        // If it's a reaction, skip it completely to avoid cluttering the DB
        if (msg.type === 'reaction') {
            return;
        }

        // Resolve the text content
        let textContent = msg.body ? msg.body.trim() : '';
        
        // If the body is empty but there is media, log the type of media
        if (!textContent && msg.hasMedia) {
            textContent = `[Media: ${msg.type || 'Attachment'}]`;
        }

        // If it's still empty, it's a system message, ciphertext, or junk - skip it!
        if (!textContent) {
            return;
        }

        const chat = await msg.getChat();
        const chatType = chat.isGroup ? 'Group' : 'Private';

        const messageData = {
            message_id: msg.id._serialized,
            group_id: chat.id._serialized,
            group_name: chat.name || 'Unknown Chat',
            sender: msg.author || msg.from,
            text: textContent,
        };

        // Push to Python Agent if it's a private chat
        if (!chat.isGroup) {
            axios.post(AGENT_WEBHOOK_URL, {
                chatId: chat.id._serialized,
                sender: messageData.sender,
                text: textContent,
                messageId: messageData.message_id
            }).catch(err => {
                console.error(`Agent webhook error: ${err.message}`);
            });
        }
        // For group chats: check if the owner is @mentioned or replied to
        else if (ownerWhatsAppId && !msg.fromMe) {
            const config = loadConfig();
            const groupId = chat.id._serialized;

            // Check if this group is in the allowed list
            const allowedGroups = config.whatsapp?.autoresponder?.allowed_groups || [];
            if (allowedGroups.includes(groupId)) {
                try {
                    let shouldRespond = false;

                    // Check @mentions
                    const mentions = await msg.getMentions();
                    const ownerMentioned = mentions.some(m => m.id.user === ownerWhatsAppId);
                    if (ownerMentioned) {
                        shouldRespond = true;
                    }

                    // Check if replying to the owner's message
                    if (!shouldRespond && msg.hasQuotedMsg) {
                        try {
                            const quotedMsg = await msg.getQuotedMessage();
                            const quotedSender = quotedMsg.from || (quotedMsg.sender && quotedMsg.sender.user);
                            if (quotedSender === ownerWhatsAppId + '@c.us' || quotedSender === ownerWhatsAppId) {
                                shouldRespond = true;
                            }
                        } catch (e) {
                            // quoted message may have been deleted
                        }
                    }

                    if (shouldRespond) {
                        console.log(`Owner mentioned/replied in group ${messageData.group_name} by ${messageData.sender}`);
                        axios.post(AGENT_WEBHOOK_URL, {
                            chatId: groupId,
                            sender: messageData.sender,
                            text: textContent,
                            messageId: messageData.message_id,
                            isGroup: true,
                            groupName: messageData.group_name
                        }).catch(err => {
                            console.error(`Agent webhook error (group): ${err.message}`);
                        });
                    }
                } catch (e) {
                    console.error(`Error checking mentions in group: ${e.message}`);
                }
            }
        }

        // Upsert contact into contacts table for name → ID resolution
        const contactStmt = db.prepare(`INSERT INTO contacts (chat_id, display_name, last_seen)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET display_name = excluded.display_name, last_seen = CURRENT_TIMESTAMP`);
        contactStmt.run(messageData.group_id, messageData.group_name);
        contactStmt.finalize();

        const stmt = db.prepare(`INSERT OR IGNORE INTO whatsapp_messages 
            (message_id, group_id, group_name, sender, text) VALUES (?, ?, ?, ?, ?)`);
        
        stmt.run(
            messageData.message_id, 
            messageData.group_id, 
            messageData.group_name,
            messageData.sender, 
            messageData.text, 
            function(err) {
                if (err) {
                    console.error('Error inserting message:', err.message);
                } else {
                    console.log(`Successfully logged ${chatType} message from ${messageData.sender} in ${messageData.group_name}: ${messageData.text.substring(0, 30)}...`);
                }
            }
        );
        stmt.finalize();
    } catch (e) {
        console.error('Error processing message:', e);
    }
});

client.initialize();
