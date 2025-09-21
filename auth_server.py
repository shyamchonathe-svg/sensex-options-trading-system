#!/usr/bin/env python3
"""
Zerodha Auth Server - Automated Postback Handler for EC2
Handles HTTPS callbacks from sensexbot.ddns.net:443
Supports TEST, LIVE, and PAPER modes
"""
import asyncio
import json
import secrets
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
import os
import sys

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from kiteconnect import KiteConnect
import uvicorn
import httpx

from secure_config_manager import SecureConfigManager

# Setup logging to both console and file
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'auth_server.log', mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load configuration from your EC2 .env
config = SecureConfigManager('.env')

# Get runtime environment variables for server binding
HOST = os.getenv('HOST', config.POSTBACK_HOST)
PORT = int(os.getenv('PORT', config.POSTBACK_PORT))
USE_HTTPS = os.getenv('HTTPS', 'False').lower() == 'true'

logger.info(f"✅ Config loaded - Mode: {config.MODE}, HTTPS: {USE_HTTPS}")
logger.info(f"📡 Server binding to: {HOST}:{PORT}")

class AuthManager:
    """Manages authentication state and token exchange with mode-specific behavior."""
    
    def __init__(self):
        self.pending_auths: Dict[str, Dict[str, Any]] = {}
        
        # Mode-specific KiteConnect initialization
        if config.MODE == "TEST":
            # Mock KiteConnect for testing
            logger.info("🧪 TEST MODE: Using Mock KiteConnect")
            self.kite = self._create_mock_kite()
        else:
            # Real KiteConnect for LIVE/PAPER
            self.kite = KiteConnect(api_key=config.ZAPI_KEY)
            logger.info(f"🔗 {config.MODE} MODE: Real KiteConnect initialized")
        
        # Ensure auth data directory exists
        Path('auth_data').mkdir(exist_ok=True)
        logger.info(f"✅ AuthManager initialized - KiteConnect {'mock' if config.MODE == 'TEST' else 'ready'}")
    
    def _create_mock_kite(self):
        """Create a mock KiteConnect for TEST mode."""
        class MockKiteConnect:
            def login_url(self, callback_url):
                return f"https://kite.zerodha.com/connect/login?api_key={config.ZAPI_KEY}&v=3&state=mock_test"
            
            def generate_session(self, request_token, api_secret):
                return {
                    "access_token": "mock_access_token_" + secrets.token_hex(16),
                    "user_id": "TEST12345",
                    "public_token": "mock_public_token",
                    "user_profile": {"email": "test@example.com", "name": "Test User"}
                }
        
        return MockKiteConnect()
    
    def generate_auth_url(self, state: str) -> Dict[str, str]:
        """Generate Zerodha login URL with postback callback."""
        try:
            # Build postback URL based on runtime config
            protocol = 'https' if USE_HTTPS else 'http'
            postback_url = f"{protocol}://{HOST}:{PORT}/postback"
            
            logger.info(f"🔗 Generating auth for state {state[:8]}... -> {postback_url}")
            
            # Create login URL with callback
            login_url = self.kite.login_url(callback_url=postback_url)
            
            # Store pending auth session with mode info
            self.pending_auths[state] = {
                'created_at': datetime.now(),
                'postback_url': postback_url,
                'login_url': login_url,
                'status': 'pending',
                'chat_id': config.TELEGRAM_CHAT_ID,
                'mode': config.MODE,
                'expires_at': datetime.now() + timedelta(seconds=config.AUTH_TIMEOUT)
            }
            
            logger.info(f"✅ Auth URL ready for {state[:8]}... in {config.MODE} mode (timeout: {config.AUTH_TIMEOUT}s)")
            return {
                'success': True,
                'state': state,
                'login_url': login_url,
                'postback_url': postback_url,
                'mode': config.MODE,
                'expires_in': config.AUTH_TIMEOUT
            }
            
        except Exception as e:
            logger.error(f"❌ Auth URL generation failed for {state[:8]}...: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to generate login URL: {str(e)}")
    
    async def handle_postback(self, state: str, request_token: str) -> Dict[str, Any]:
        """Process Zerodha postback and exchange token with mode-specific logic."""
        
        # Validate pending auth exists
        if state not in self.pending_auths:
            logger.warning(f"⚠️  Postback with unknown state: {state[:8]}...")
            raise HTTPException(status_code=400, detail="Invalid authentication session")
        
        auth_state = self.pending_auths[state]
        
        # Check processing status
        if auth_state['status'] != 'pending':
            logger.warning(f"⚠️  State {state[:8]}... already {auth_state['status']}")
            raise HTTPException(status_code=400, detail="Session already processed")
        
        # Check session expiry
        if datetime.now() > auth_state['expires_at']:
            del self.pending_auths[state]
            logger.warning(f"⚠️  Expired session in postback: {state[:8]}...")
            raise HTTPException(status_code=400, detail="Session expired")
        
        # Validate request token
        if not request_token or len(request_token) < 8:
            logger.warning(f"⚠️  Invalid request_token: {len(request_token) if request_token else 0} chars")
            raise HTTPException(status_code=400, detail="Invalid request token")
        
        try:
            logger.info(f"🔄  Exchanging token for {state[:8]}... in {config.MODE} mode (RT: {request_token[:8]}...)")
            
            # Mode-specific token exchange
            if config.MODE == "TEST":
                response = self.kite.generate_session(request_token, config.ZAPI_SECRET)
            else:
                # Real exchange for LIVE/PAPER
                response = self.kite.generate_session(request_token, api_secret=config.ZAPI_SECRET)
            
            access_token = response["access_token"]
            
            logger.info(f"✅ Exchange complete for {state[:8]}... ({config.MODE} mode, AT length: {len(access_token)})")
            
            # Update .env file atomically
            token_saved = config.update_access_token(access_token)
            
            # Update auth state for audit
            auth_state.update({
                'status': 'completed' if token_saved else 'token_save_failed',
                'access_token_preview': access_token[:8] + "...",
                'request_token': request_token,
                'completed_at': datetime.now(),
                'token_saved': token_saved,
                'token_length': len(access_token),
                'mode': config.MODE
            })
            
            # Cleanup and archive
            del self.pending_auths[state]
            await self._archive_result(auth_state)
            
            # Notify success/failure
            if token_saved:
                asyncio.create_task(self._send_success_notification(access_token, state))
            else:
                asyncio.create_task(self._send_failure_notification(state, "Failed to save token"))
            
            return {
                'success': token_saved,
                'state': state,
                'access_token_preview': access_token[:8] + "...",
                'token_length': len(access_token),
                'expiry': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d 09:00 IST'),
                'mode': config.MODE,
                'trading_mode': config.MODE
            }
            
        except Exception as e:
            logger.error(f"💥 Token exchange failed for {state[:8]}... in {config.MODE} mode: {e}", exc_info=True)
            
            auth_state.update({
                'status': 'exchange_failed',
                'error': str(e),
                'completed_at': datetime.now(),
                'mode': config.MODE
            })
            
            await self._archive_result(auth_state)
            asyncio.create_task(self._send_failure_notification(state, str(e)))
            
            raise HTTPException(status_code=500, detail=f"Token exchange failed: {str(e)}")
    
    async def _archive_result(self, auth_data: Dict[str, Any]):
        """Archive authentication result to auth_data/."""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            status = auth_data.get('status', 'unknown')
            mode = auth_data.get('mode', 'unknown')
            filename = f"auth_data/auth_{mode}_{status}_{timestamp}.json"
            
            # Sanitize sensitive data
            safe_data = auth_data.copy()
            for key in ['access_token', 'request_token', 'access_token_preview']:
                safe_data.pop(key, None)
            
            with open(filename, 'w') as f:
                json.dump(safe_data, f, indent=2)
            
            logger.debug(f"📁 Archived: {filename}")
            
        except Exception as e:
            logger.error(f"❌ Archive failed: {e}")
    
    async def _send_success_notification(self, access_token: str, state: str):
        """Send Telegram success notification with mode info."""
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
            expiry = datetime.now() + timedelta(days=1)
            
            # Mode-specific messages
            if config.MODE == "TEST":
                mode_msg = "🧪 <b>TEST MODE</b> - Mock token generated"
                token_msg = f"🔑 <b>Mock Token:</b> <code>{access_token[:8]}...</code>"
            elif config.MODE == "PAPER":
                mode_msg = "📝 <b>PAPER MODE</b> - Simulated trading ready"
                token_msg = f"🔑 <b>Paper Token:</b> <code>{access_token[:8]}...</code>"
            else:  # LIVE
                mode_msg = "🔴 <b>LIVE MODE</b> - Real trading active"
                token_msg = f"🔑 <b>Live Token:</b> <code>{access_token[:8]}...</code>"
            
            message = (
                f"🔐 <b>Authentication Complete!</b>\n\n"
                f"{mode_msg}\n"
                f"{token_msg}\n"
                f"📏 <b>Length:</b> {len(access_token)} characters\n"
                f"⏰ <b>Expires:</b> {expiry.strftime('%Y-%m-%d 09:00 IST')}\n"
                f"🌐 <b>Server:</b> {HOST}:{PORT}\n"
                f"🔑 <b>Session:</b> <code>{state[:8]}...</code>\n"
                f"⚙️ <b>Protocol:</b> {'🔒 HTTPS' if USE_HTTPS else '🔓 HTTP'}\n\n"
                f"📁 <b>EC2 .env:</b> Updated (chmod 600)\n"
                f"🎉 <b>Fully Automated!</b> No copy-paste needed"
            )
            
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    'chat_id': config.TELEGRAM_CHAT_ID,
                    'text': message,
                    'parse_mode': 'HTML'
                })
                
                if resp.status_code == 200:
                    logger.info(f"📱 Success notification sent for {state[:8]}... ({config.MODE} mode)")
                else:
                    logger.warning(f"⚠️  Telegram notification failed: {resp.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ Success notification failed: {e}")
    
    async def _send_failure_notification(self, state: str, error: str):
        """Send Telegram failure notification."""
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
            
            mode_icon = {"TEST": "🧪", "PAPER": "📝", "LIVE": "🔴"}.get(config.MODE, "⚙️")
            
            message = (
                f"🚨 <b>Authentication Failed</b>\n\n"
                f"{mode_icon} <b>{config.MODE} Mode</b>\n"
                f"❌ <b>Error Details:</b>\n"
                f"🔑 <b>Session:</b> <code>{state[:8]}...</code>\n"
                f"💥 <b>Issue:</b> {error[:100]}...\n\n"
                f"💡 <b>Try Again:</b>\n"
                f"   • Use <code>/auth</code> command\n"
                f"   • Complete within {config.AUTH_TIMEOUT // 60} minutes\n\n"
                f"📊 <b>Debug Info:</b>\n"
                f"   • Check: <code>tail -f logs/auth_server.log</code>\n"
                f"   • .env: {'.env exists' if os.path.exists('.env') else '.env missing'}\n"
                f"   • API: {config.ZAPI_KEY[:8]}...\n"
                f"   • Mode: {config.MODE}"
            )
            
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={
                    'chat_id': config.TELEGRAM_CHAT_ID,
                    'text': message,
                    'parse_mode': 'HTML'
                })
            
            logger.info(f"📱 Failure notification sent for {state[:8]}... ({config.MODE} mode)")
            
        except Exception as e:
            logger.error(f"❌ Failure notification failed: {e}")
    
    def cleanup_expired(self) -> int:
        """Remove expired authentication sessions."""
        now = datetime.now()
        expired_count = 0
        
        for state in list(self.pending_auths):
            if now > self.pending_auths[state]['expires_at']:
                logger.info(f"🧹 Cleaning expired session: {state[:8]}... ({self.pending_auths[state].get('mode', 'unknown')} mode)")
                del self.pending_auths[state]
                expired_count += 1
        
        return expired_count

# Initialize the auth manager
auth_manager = AuthManager()

# Create FastAPI app
app = FastAPI(
    title="Sensex Trading Auth Server",
    description=f"Automated Zerodha authentication for EC2 deployment - {config.MODE} Mode",
    version="2.1.0"
)

@app.get("/", response_class=HTMLResponse)
async def root():
    """Main dashboard for auth server with mode-specific styling."""
    pending = len(auth_manager.pending_auths)
    cleaned = auth_manager.cleanup_expired()
    
    # Mode-specific styling
    if config.MODE == "TEST":
        mode_style = "background: #f0f8ff; color: #0066cc;"
        mode_emoji = "🧪"
    elif config.MODE == "PAPER":
        mode_style = "background: #f5f5f5; color: #666666;"
        mode_emoji = "📝"
    else:  # LIVE
        mode_style = "background: #ffebee; color: #c62828;"
        mode_emoji = "🔴"
    
    protocol_display = "🔒 HTTPS" if USE_HTTPS else "🔓 HTTP"
    
    html = f"""
    <html>
    <head>
        <title>Sensex Auth Server - {config.MODE} Mode</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; margin: 0; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .mode-badge {{ padding: 8px 16px; border-radius: 20px; font-weight: bold; margin: 10px 0; }}
            .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
            .status-card {{ padding: 15px; border-radius: 8px; border-left: 4px solid #4CAF50; background: #f9f9f9; }}
            .quick-links {{ display: flex; flex-wrap: wrap; gap: 10px; }}
            a {{ color: #2196F3; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Sensex Trading Auth Server {mode_emoji}</h1>
            <div class="mode-badge" style="{mode_style}">{config.MODE} MODE</div>
            
            <div class="status-grid">
                <div class="status-card">
                    <strong>Status:</strong> ✅ Active<br>
                    <strong>Protocol:</strong> {protocol_display}
                </div>
                <div class="status-card">
                    <strong>Server:</strong> {HOST}:{PORT}<br>
                    <strong>Pending Auths:</strong> {pending}
                </div>
                <div class="status-card">
                    <strong>Cleaned Expired:</strong> {cleaned}<br>
                    <strong>Last Cleanup:</strong> {datetime.now().strftime('%H:%M:%S')}
                </div>
            </div>
            
            <hr>
            <h3>Quick Links:</h3>
            <div class="quick-links">
                <a href="/health">/health</a> •
                <a href="/auth/generate">/auth/generate</a> •
                <a href="/pending">/pending</a> •
                <a href="/docs">/docs</a>
            </div>
            <hr>
            <p><small>EC2 Deployment • .env secured • {config.MODE} Mode Active</small></p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/health")
async def health():
    """Health check endpoint with mode info."""
    cleaned = auth_manager.cleanup_expired()
    
    # Mode-specific health info
    if config.MODE == "TEST":
        kite_status = "🧪 MOCK KiteConnect - No real API calls"
    elif config.MODE == "PAPER":
        kite_status = "📝 PAPER KiteConnect - Simulated trades"
    else:
        kite_status = "🔴 LIVE KiteConnect - Real trading"
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "pending_auths": len(auth_manager.pending_auths),
        "cleaned_expired": cleaned,
        "mode": config.MODE,
        "trading_mode": config.MODE,
        "server": f"{HOST}:{PORT}",
        "protocol": "HTTPS" if USE_HTTPS else "HTTP",
        "kite_status": kite_status,
        "token_valid": bool(config.ACCESS_TOKEN),
        "auth_url": f"{'https' if USE_HTTPS else 'http'}://{HOST}:{PORT}/auth/generate",
        "postback_url": f"{'https' if USE_HTTPS else 'http'}://{HOST}:{PORT}/postback"
    }

@app.get("/auth/generate")
async def generate_auth(state: Optional[str] = Query(None)):
    """Generate login URL for Telegram bot."""
    if not state:
        state = secrets.token_urlsafe(32)
    
    try:
        return auth_manager.generate_auth_url(state)
    except Exception as e:
        logger.error(f"Auth generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/postback")
async def postback(state: str, request_token: str):
    """Zerodha postback handler."""
    logger.info(f"📥 Postback received: state={state[:8]}..., token={request_token[:8]}..., mode={config.MODE}")
    
    try:
        result = await auth_manager.handle_postback(state, request_token)
        return RedirectResponse(f"/success?state={state}&token={result.get('access_token_preview', 'unknown')}&mode={config.MODE}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Postback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/success")
async def success(state: str, token: str = "", mode: str = ""):
    """Success page after auth with mode-specific styling."""
    # Mode-specific styling
    if mode == "TEST":
        bg_color = "#e3f2fd"
        text_color = "#1976d2"
        emoji = "🧪"
    elif mode == "PAPER":
        bg_color = "#f5f5f5"
        text_color = "#616161"
        emoji = "📝"
    else:
        bg_color = "#ffebee"
        text_color = "#c62828"
        emoji = "🔴"
    
    html = f"""
    <html>
    <head>
        <title>Auth Success - {mode} Mode</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                   text-align: center; padding: 50px; 
                   background: {bg_color}; color: {text_color}; margin: 0; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            h1 {{ font-size: 3em; margin-bottom: 20px; }}
            .success-box {{ background: white; padding: 30px; border-radius: 10px; 
                          box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin: 20px 0; }}
            a {{ color: {text_color}; text-decoration: none; font-weight: bold; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{emoji} Success!</h1>
            <div class="success-box">
                <h2>Your trading bot has been updated!</h2>
                <p><strong>Mode:</strong> {mode} Trading</p>
                <p><strong>Token:</strong> {token}</p>
                <p><strong>Session:</strong> {state[:8]}...</p>
                <p><em>Authentication complete. You can close this window.</em></p>
            </div>
            <a href="/">← Back to Dashboard</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/pending")
async def pending():
    """Show pending auth requests with mode info."""
    cleaned = auth_manager.cleanup_expired()
    
    pending_list = []
    for state, data in auth_manager.pending_auths.items():
        pending_list.append({
            "state": state[:8] + "...",
            "mode": data.get("mode", "unknown"),
            "created": data["created_at"].strftime("%H:%M:%S"),
            "expires": data["expires_at"].strftime("%H:%M:%S"),
            "url": data["login_url"][:50] + "..." if len(data["login_url"]) > 50 else data["login_url"]
        })
    
    return {
        "pending_count": len(auth_manager.pending_auths),
        "cleaned": cleaned,
        "mode": config.MODE,
        "server": f"{HOST}:{PORT}",
        "protocol": "HTTPS" if USE_HTTPS else "HTTP",
        "pending_sessions": pending_list
    }

@app.get("/mode")
async def get_mode_info():
    """Get current mode configuration."""
    return {
        "current_mode": config.MODE,
        "description": {
            "TEST": "🧪 Internal testing with mock data - no real API calls",
            "PAPER": "📝 Paper trading with real market data - simulated positions",
            "LIVE": "🔴 Live trading with real money - actual positions executed"
        }[config.MODE],
        "server_config": {
            "host": HOST,
            "port": PORT,
            "protocol": "HTTPS" if USE_HTTPS else "HTTP",
            "external_access": HOST != "127.0.0.1"
        },
        "api_status": {
            "kiteconnect": "mock" if config.MODE == "TEST" else "real",
            "token_valid": bool(config.ACCESS_TOKEN),
            "auth_timeout": config.AUTH_TIMEOUT
        }
    }

if __name__ == "__main__":
    # Determine SSL configuration
    ssl_keyfile = None
    ssl_certfile = None
    
    if USE_HTTPS:
        # Try to load SSL certificates
        ssl_cert_path = os.getenv('SSL_CERT_PATH', '/etc/letsencrypt/live/sensexbot.ddns.net/fullchain.pem')
        ssl_key_path = os.getenv('SSL_KEY_PATH', '/etc/letsencrypt/live/sensexbot.ddns.net/privkey.pem')
        
        if os.path.exists(ssl_cert_path) and os.path.exists(ssl_key_path):
            ssl_certfile = ssl_cert_path
            ssl_keyfile = ssl_key_path
            logger.info(f"🔒 SSL enabled - Cert: {ssl_cert_path}")
        else:
            logger.warning(f"⚠️  HTTPS requested but SSL files not found:")
            logger.warning(f"   Cert: {ssl_cert_path} ({'EXISTS' if os.path.exists(ssl_cert_path) else 'MISSING'})")
            logger.warning(f"   Key: {ssl_key_path} ({'EXISTS' if os.path.exists(ssl_key_path) else 'MISSING'})")
            logger.warning("   Falling back to HTTP")
            ssl_certfile = None
            ssl_keyfile = None
    
    # Final server config
    protocol = "HTTPS" if (USE_HTTPS and ssl_certfile and ssl_keyfile) else "HTTP"
    postback_url = f"{protocol.lower()}://{HOST}:{PORT}/postback"
    
    logger.info(f"🚀 Starting server on {HOST}:{PORT}")
    logger.info(f"🔒 {protocol} ({'SSL enabled' if ssl_certfile else 'HTTP fallback'})")
    logger.info(f"📍 Postback URL: {postback_url}")
    logger.info(f"⚙️  Trading Mode: {config.MODE}")
    
    # Start the server
    uvicorn.run(
        "auth_server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile
    )
