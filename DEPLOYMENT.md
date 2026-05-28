# Deployment Guide

This guide covers production deployment considerations for the Voice AI Tools Flask backend.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Configuration](#environment-configuration)
- [Security Configuration](#security-configuration)
- [Deployment Options](#deployment-options)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [Backup and Recovery](#backup-and-recovery)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements

- **Python**: 3.9 or higher
- **Memory**: 4GB+ RAM minimum (8GB+ recommended for Coqui TTS)
- **Disk**: 10GB+ free space (2GB for Coqui model, additional for voice samples)
- **OS**: Linux (Ubuntu 20.04+ recommended), macOS, or Windows with WSL2

### Required Dependencies

```bash
# Core dependencies
flask>=3.0.3,<4.0.0
flask-cors>=6.0.0,<7.0.0
flask-limiter>=3.5.1,<4.0.0
google-genai>=0.8.0,<1.0.0
python-dotenv>=1.2.2,<2.0.0

# Optional dependencies
TTS>=0.22.0,<1.0.0  # For local voice cloning (Coqui XTTS v2)
psutil>=5.9.0,<6.0.0  # For enhanced health monitoring
```

## Environment Configuration

### Required Variables

```bash
# Google Gemini API key (required for TTS)
GOOGLE_API_KEY=your_google_gemini_api_key_here
```

### Recommended for Production

```bash
# Shared secret for authentication
VOICE_SERVER_TOKEN=your_strong_random_token_here

# Set to production mode
FLASK_ENV=production
```

### Optional Configuration

```bash
# Shodan API key for OSINT lookups
SHODAN_API_KEY=your_shodan_api_key_here

# Server configuration
PORT=5001
ALLOW_NETWORK_BINDING=0  # Keep as 0 for security

# Request signing (replay protection)
ENABLE_REQUEST_SIGNING=true
SIGNING_TOLERANCE_SECONDS=300

# Custom TTS model
GOOGLE_TTS_MODEL=gemini-2.5-flash-preview-tts

# CORS origins (comma-separated)
ALLOWED_ORIGINS=chrome-extension://YOUR_EXTENSION_ID,https://yourdomain.com
```

## Security Configuration

### Authentication

1. **Set VOICE_SERVER_TOKEN**: Always set a strong random token in production
2. **Enable Request Signing**: Set `ENABLE_REQUEST_SIGNING=true` for replay protection
3. **Use HTTPS**: Deploy behind a reverse proxy (nginx/Apache) with SSL/TLS

### Network Security

1. **Keep ALLOW_NETWORK_BINDING=0**: Server binds to 127.0.0.1 only
2. **Use Firewall**: Restrict access to specific IPs if needed
3. **Configure CORS**: Only allow trusted origins in ALLOWED_ORIGINS

### Data Protection

1. **API Keys**: Never commit API keys to version control
2. **Voice Samples**: Store in secure directory with proper permissions
3. **Logs**: Rotate logs regularly and avoid logging sensitive data

## Deployment Options

### Option 1: Systemd Service (Linux)

Create `/etc/systemd/system/voice-ai-tools.service`:

```ini
[Unit]
Description=Voice AI Tools Flask Server
After=network.target

[Service]
Type=simple
User=voiceai
WorkingDirectory=/opt/voice-ai-tools
Environment="PATH=/opt/voice-ai-tools/venv/bin"
ExecStart=/opt/voice-ai-tools/venv/bin/python flask_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable voice-ai-tools
sudo systemctl start voice-ai-tools
sudo systemctl status voice-ai-tools
```

### Option 2: Docker Deployment

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m voiceai && chown -R voiceai:voiceai /app
USER voiceai

# Expose port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1

CMD ["python", "flask_server.py"]
```

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  voice-ai-tools:
    build: .
    ports:
      - "127.0.0.1:5001:5001"
    environment:
      - GOOGLE_API_KEY=${GOOGLE_API_KEY}
      - VOICE_SERVER_TOKEN=${VOICE_SERVER_TOKEN}
      - FLASK_ENV=production
    volumes:
      - voice_samples:/app/voice_samples
      - voice_embeddings:/app/voice_embeddings
      - backups:/app/backups
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  voice_samples:
  voice_embeddings:
  backups:
```

Run with Docker Compose:
```bash
docker-compose up -d
```

### Option 3: Cloud Deployment (AWS/GCP/Azure)

#### AWS EC2

1. Launch Ubuntu 20.04+ instance
2. Install dependencies and set up systemd service
3. Configure Security Group to allow HTTPS (443) only
4. Set up Application Load Balancer with SSL certificate
5. Use Route53 for domain management

#### Google Cloud Run

Create `cloudbuild.yaml`:

```yaml
steps:
  - name: 'python:3.11'
    entrypoint: 'python'
    args: ['-m', 'pip', 'install', '-r', 'requirements.txt']
  
  - name: 'python:3.11'
    entrypoint: 'python'
    args: ['flask_server.py']

# Deploy to Cloud Run
# gcloud run deploy voice-ai-tools --source .
```

## Monitoring and Maintenance

### Health Checks

Monitor the `/health` endpoint regularly:

```bash
curl http://localhost:5001/health
```

Key metrics to monitor:
- `status`: Should be "ok"
- `tts_engine`: Should be true
- `api_key_configured`: Should be true
- `uptime_seconds`: Track server uptime
- `memory_mb`: Monitor memory usage
- `cpu_percent`: Monitor CPU usage
- `disk_gb_free`: Ensure sufficient disk space

### Log Management

1. **Configure log rotation**: Use logrotate or systemd logging
2. **Centralized logging**: Consider ELK stack, CloudWatch, or similar
3. **Alert on errors**: Set up alerts for error patterns in logs

### Performance Monitoring

1. **Response times**: Monitor TTS synthesis response times
2. **Error rates**: Track failed requests and error patterns
3. **Resource usage**: Monitor CPU, memory, and disk usage

### Updates and Maintenance

1. **Regular updates**: Keep dependencies updated regularly
2. **Security patches**: Apply security updates promptly
3. **Backup before updates**: Always backup before major updates

## Backup and Recovery

### Automated Backups

Use the built-in backup manager:

```bash
# Create backup
python backup_manager.py create my_backup

# Automatic backup (keeps last 10)
python backup_manager.py auto 10

# List backups
python backup_manager.py list

# Restore backup
python backup_manager.py restore my_backup
```

### Backup Strategy

1. **Frequency**: Daily automated backups
2. **Retention**: Keep last 30 days of backups
3. **Offsite storage**: Copy backups to cloud storage (S3, GCS, etc.)
4. **Test restores**: Regularly test backup restoration

### Critical Data to Backup

- Voice embeddings (`voice_embeddings/`)
- Voice samples (`voice_samples/`)
- Custom voice configuration (`custom_voice_config.py`)
- Voice presets (`voice_presets.json`)
- Session logs (`session_log.json`)

### Disaster Recovery

1. **Document recovery procedures**: Keep step-by-step recovery guide
2. **Practice recovery drills**: Test disaster recovery procedures regularly
3. **Monitor backup health**: Alert on backup failures

## Troubleshooting

### Common Issues

#### Server Won't Start

```bash
# Check if port is already in use
lsof -i :5001

# Check Python dependencies
pip install -r requirements.txt

# Check environment variables
python -c "import os; print(os.environ.get('GOOGLE_API_KEY'))"
```

#### TTS Not Working

```bash
# Check API key configuration
curl http://localhost:5001/health

# Test Google API key
python -c "from google import genai; client = genai.Client(api_key='YOUR_KEY')"
```

#### Voice Cloning Fails

```bash
# Check Coqui installation
python -c "from TTS.api import TTS; print('Coqui installed')"

# Check cloned status
curl -H "X-Voice-Token: YOUR_TOKEN" http://localhost:5001/cloned_status

# Install Coqui if needed
pip install TTS
```

#### High Memory Usage

```bash
# Check memory usage
curl http://localhost:5001/health | grep memory_mb

# Restart server if memory leak suspected
sudo systemctl restart voice-ai-tools
```

### Performance Issues

1. **Slow TTS response**: Check network latency to Google API
2. **High CPU usage**: Check if Coqui model is being used unnecessarily
3. **Disk space full**: Clean up old voice samples and backups

### Security Issues

1. **Unauthorized access**: Check VOICE_SERVER_TOKEN is set correctly
2. **Rate limiting**: Adjust flask-limiter settings if needed
3. **CORS issues**: Verify ALLOWED_ORIGINS configuration

## Additional Resources

- [README.md](README.md) - Project overview and quick start
- [.env.example](.env.example) - Environment variable reference
- [openapi.json](openapi.json) - API documentation
- [backup_manager.py](backup_manager.py) - Backup utility documentation

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review application logs for error messages
3. Check the `/health` endpoint for system status
4. Consult the API documentation at `/api/docs`