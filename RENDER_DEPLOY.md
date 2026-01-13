# 🚀 Deploy to Render - Step by Step Guide

## Prerequisites
1. GitHub account
2. Render account (free tier works)
3. Telegram Bot Token from @BotFather

## Step 1: Prepare Your Code

### 1.1 Push to GitHub
```bash
# Initialize git (if not already)
git init
git add .
git commit -m "Initial commit - CC Checker Bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 1.2 Important Files Created
- ✅ `requirements.txt` - Python dependencies
- ✅ `Procfile` - Tells Render how to run the bot
- ✅ `runtime.txt` - Python version
- ✅ `.gitignore` - Excludes sensitive files

## Step 2: Deploy on Render

### 2.1 Create New Service
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **"New +"** → **"Background Worker"**

### 2.2 Configure Service

**Connect Repository:**
- Connect your GitHub account
- Select your repository
- Choose the branch (usually `main`)

**Basic Settings:**
- **Name:** `cc-checker-bot` (or any name)
- **Environment:** `Python 3`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`

**Environment Variables:**
Click "Add Environment Variable" and add:
```
BOT_TOKEN = your_telegram_bot_token_here
```

**Plan:**
- Choose **Free** plan (or paid if needed)
- Free tier gives you 750 hours/month

### 2.3 Deploy
1. Click **"Create Background Worker"**
2. Render will automatically:
   - Clone your repo
   - Install dependencies
   - Start your bot

### 2.4 Monitor
- Watch the logs in Render dashboard
- You should see: "🔥 ULTIMATE CC CHECKER v5.0 - ENHANCED 🔥"
- Test your bot on Telegram

## Step 3: Verify Deployment

### 3.1 Check Logs
In Render dashboard, go to **"Logs"** tab:
- Should see: "🚀 Bot is starting..."
- Should see: "✅ Bot is running..."

### 3.2 Test Bot
1. Open Telegram
2. Find your bot
3. Send `/start` or `/help`
4. Bot should respond!

## Step 4: Keep Bot Running (Free Tier)

**Important for Free Tier:**
- Free tier services **sleep after 15 minutes of inactivity**
- To keep it awake, you can:
  1. Use a cron job (Render Cron Jobs - paid)
  2. Use external ping service (free)
  3. Upgrade to paid plan

**Free Ping Service:**
- Use [UptimeRobot](https://uptimerobot.com) (free)
- Set up HTTP monitor to ping your bot
- Or use [cron-job.org](https://cron-job.org) to ping periodically

## Troubleshooting

### Bot Not Responding?
1. **Check Logs:** Look for errors in Render logs
2. **Check BOT_TOKEN:** Make sure it's set correctly
3. **Check Build:** Ensure `requirements.txt` is correct
4. **Restart Service:** Click "Manual Deploy" → "Clear build cache & deploy"

### Import Errors?
- Make sure all packages in `requirements.txt` are correct
- Check Python version matches `runtime.txt`

### Bot Goes to Sleep?
- Free tier limitation
- Use ping service or upgrade plan
- Or manually wake it by sending a message

### File Storage Issues?
- Render's filesystem is **ephemeral** (resets on restart)
- For persistent storage, use:
  - Render Disk (paid)
  - External database (PostgreSQL, MongoDB)
  - Cloud storage (S3, etc.)

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ Yes | Telegram bot token from @BotFather |
| `MAX_CHECKS_PER_MINUTE` | ❌ No | Rate limit (default: 15) |
| `BULK_MAX_CARDS` | ❌ No | Max cards per bulk (default: 100) |
| `BULK_WORKERS` | ❌ No | Thread workers (default: 12) |
| `API_TIMEOUT` | ❌ No | API timeout seconds (default: 30) |

## Updating Your Bot

1. Make changes to `bot.py`
2. Commit and push to GitHub:
   ```bash
   git add .
   git commit -m "Update bot"
   git push
   ```
3. Render will **auto-deploy** (if auto-deploy enabled)
4. Or manually deploy from Render dashboard

## Security Notes

⚠️ **Important:**
- Never commit `BOT_TOKEN` to GitHub
- Use environment variables in Render
- Keep `.env` in `.gitignore`
- Don't share your bot token publicly

## Cost Estimate

**Free Tier:**
- ✅ 750 hours/month
- ✅ Auto-deploy from GitHub
- ✅ HTTPS endpoints
- ⚠️ Services sleep after inactivity
- ⚠️ Limited resources

**Paid Plans:**
- Starter: $7/month - Always on, more resources
- Professional: $25/month - Better performance

## Support

If you encounter issues:
1. Check Render logs
2. Check bot logs in Telegram
3. Verify environment variables
4. Check GitHub repository is connected

---

**🎉 Your bot should now be live on Render!**
