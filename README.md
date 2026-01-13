# 🔥 Ultimate CC Checker Bot v5.0

A powerful Telegram bot for credit card validation with multiple API support, statistics tracking, and advanced features.

## ✨ Features

- ✅ **Multiple API Support**: CHKR.CC, Stripe, Braintree
- ✅ **Auto-Shop Testing**: Test cards on merchant sites
- ✅ **Bulk Processing**: Check up to 100 cards at once
- ✅ **File Upload**: Support for .txt file uploads
- ✅ **Statistics & History**: Track all checks
- ✅ **Rate Limiting**: Prevent abuse
- ✅ **Progress Updates**: Real-time bulk check progress
- ✅ **Multi-API Checks**: Parallel checking with all APIs
- ✅ **Proxy Support**: Rotate proxies automatically
- ✅ **BIN Lookup**: Get card information

## 🚀 Quick Start

### Local Development

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd cc-checcker
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set environment variable**
```bash
export BOT_TOKEN=your_bot_token_here
```

4. **Run the bot**
```bash
python bot.py
```

### Deploy to Render

See [RENDER_DEPLOY.md](RENDER_DEPLOY.md) for detailed deployment instructions.

## 📋 Commands

### Core Checks
- `/check card` - CHKR.CC API Check
- `/skcheck card` - Stripe SK Auth
- `/btcheck card` - Braintree API Check
- `/multicheck card` - Multi-API Parallel Check
- `/autosh` - Auto-Shop Check
- `/bin 411111` - BIN lookup
- `/bulk` - Bulk check (text or file)
- `/skbulk` - Bulk Stripe SK check

### Management
- `/addsk sk_live_...` - Add Stripe key
- `/addbt merchant|public|private` - Add Braintree credentials
- `/addproxy host:port:user:pass` - Add proxy
- `/stats` - Show statistics
- `/recent` - Recent check history

See `/help` in the bot for full command list.

## 🔧 Configuration

Set environment variables:
- `BOT_TOKEN` - Telegram bot token (required)
- `MAX_CHECKS_PER_MINUTE` - Rate limit (default: 15)
- `BULK_MAX_CARDS` - Max cards per bulk (default: 100)
- `BULK_WORKERS` - Thread workers (default: 12)
- `API_TIMEOUT` - API timeout (default: 30)

## 📁 File Structure

```
.
├── bot.py                 # Main bot file
├── requirements.txt       # Python dependencies
├── Procfile              # Render deployment config
├── runtime.txt           # Python version
├── .env.example          # Environment variables template
├── .gitignore            # Git ignore rules
├── RENDER_DEPLOY.md      # Deployment guide
└── README.md             # This file
```

## 🔒 Security

- ✅ Rate limiting per user
- ✅ Environment variables for secrets
- ✅ Input validation
- ✅ Thread-safe operations
- ⚠️ Never commit tokens to git

## 📊 Statistics

The bot tracks:
- Total checks performed
- Live/Dead/Error counts
- Success rates
- Check history (last 1000)
- Bulk check statistics

## 🌐 Deployment

### Render (Recommended)
- Free tier available
- Auto-deploy from GitHub
- See [RENDER_DEPLOY.md](RENDER_DEPLOY.md)

### Other Platforms
- Heroku
- Railway
- DigitalOcean
- AWS/GCP/Azure

## 📝 License

This project is for educational purposes only.

## ⚠️ Disclaimer

This bot is for testing and validation purposes only. Use responsibly and in compliance with all applicable laws and terms of service.

## 🤝 Support

For issues or questions:
1. Check the logs
2. Review [RENDER_DEPLOY.md](RENDER_DEPLOY.md)
3. Check environment variables
4. Verify API credentials

---

**Made with ❤️ for the community**
