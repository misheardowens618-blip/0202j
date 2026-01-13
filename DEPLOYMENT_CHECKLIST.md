# ✅ Deployment Checklist for Render

## Before Deploying

- [ ] **GitHub Repository Created**
  - [ ] Code pushed to GitHub
  - [ ] All files committed
  - [ ] `.gitignore` includes sensitive files

- [ ] **Telegram Bot Token**
  - [ ] Got token from @BotFather
  - [ ] Token is ready to use
  - [ ] Bot is activated

- [ ] **Files Ready**
  - [x] `requirements.txt` - Dependencies
  - [x] `Procfile` - Process file
  - [x] `runtime.txt` - Python version
  - [x] `bot.py` - Main bot file
  - [x] `.gitignore` - Git ignore rules

## Render Setup

- [ ] **Create Render Account**
  - [ ] Sign up at render.com
  - [ ] Connect GitHub account

- [ ] **Create Background Worker**
  - [ ] New + → Background Worker
  - [ ] Connect repository
  - [ ] Select branch (main)

- [ ] **Configure Settings**
  - [ ] Name: `cc-checker-bot`
  - [ ] Environment: `Python 3`
  - [ ] Build Command: `pip install -r requirements.txt`
  - [ ] Start Command: `python bot.py`

- [ ] **Environment Variables**
  - [ ] Add `BOT_TOKEN` = your_token_here
  - [ ] (Optional) Add other config vars

- [ ] **Deploy**
  - [ ] Click "Create Background Worker"
  - [ ] Wait for build to complete
  - [ ] Check logs for errors

## After Deployment

- [ ] **Verify Bot Works**
  - [ ] Send `/start` to bot
  - [ ] Bot responds correctly
  - [ ] Test a check command

- [ ] **Monitor Logs**
  - [ ] Check Render logs tab
  - [ ] No errors visible
  - [ ] Bot is running

- [ ] **Keep Bot Awake (Free Tier)**
  - [ ] Set up UptimeRobot ping
  - [ ] Or use cron-job.org
  - [ ] Or upgrade to paid plan

## Important Notes

⚠️ **Free Tier Limitations:**
- Services sleep after 15 min inactivity
- Files reset on restart (ephemeral filesystem)
- Limited resources

💡 **Solutions:**
- Use external ping service to keep awake
- Use database for persistent storage (if needed)
- Upgrade to paid plan for always-on

## Quick Deploy Commands

```bash
# 1. Initialize git (if needed)
git init
git add .
git commit -m "Ready for Render deployment"

# 2. Push to GitHub
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main

# 3. Go to Render and deploy!
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot not responding | Check BOT_TOKEN in env vars |
| Build fails | Check requirements.txt |
| Import errors | Verify Python version |
| Bot sleeps | Use ping service |
| Files lost | Use external storage |

---

**Ready to deploy? Follow [RENDER_DEPLOY.md](RENDER_DEPLOY.md) for detailed steps!**
