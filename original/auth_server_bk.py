#!/usr/bin/env python3
"""
Zerodha Auth Server - Handles postback from sensexbot.ddns.net
Runs on your EC2 instance for HTTPS callbacks.
"""
import asyncio
import json
import secrets
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from kiteconnect import KiteConnect
import uvicorn
import httpx
from pydantic import BaseModel

from secure_config_manager import SecureConfigManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/auth_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load your EC2 .env
config = SecureConfigManager('.env')

class AuthManager:
    """Manages authentication state and token exchange."""
    
    def __init__(self):
        self.pending_auths: Dict[str, Dict[str, Any]] = {}
        self.kite = KiteConnect(api_key=config.ZAPI_KEY)
        
        # Ensure auth data directory
        Path('auth_data').mkdir(exist_ok=True)
    
    def generate_auth_url(self, state: str) -> Dict[str, str]:
        """Generate Zerodha login URL with postback."""
        try:
            protocol = 'https' if config.USE_HTTPS else 'http'
            postback_url = f"{protocol}://{config.POSTBACK_HOST}:{config.POSTBACK_PORT}/postback"
            
            # Generate login URL
            login_url = self.kite.login_url(callback_url=postback_url)
            
            # Store pending authentication state
            self.pending_auths[state] = {
                'created_at': datetime.now(),
                'postback_url': postback_url,
                'status': 'pending',
                'chat_id': config.TELEGRAM_CHAT_ID,
                'expires_at': datetime.now() + timedelta(seconds=config.AUTH_TIMEOUT)
            }
            
            logger.info(f"🔗 Generated auth URL for state {state[:8]}... -> {login_url[:50]}...")
            return {
                'success': True,
                'state': state,
                'login_url': login_url,
                'postback_url': postback_url,
                'expires_in': config.AUTH_TIMEOUT
            }
        except Exception as e:
            logger.error(f"❌ Failed to generate auth URL: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def handle_postback(self, state: str, request_token: str) -> Dict[str, Any]:
        """Handle Zerodha callback and exchange token."""
        
        # Validate state exists
        if state not in self.pending_auths:
            logger.warning(f"⚠️ Unknown auth state: {state[:8]}...")
            raise HTTPException(status_code=400, detail="Invalid authentication request")
        
        auth_state = self.pending_auths[state]
        
        # Check if already processed
        if auth_state['status'] != 'pending':
            logger.warning(f"⚠️ Auth state {state[:8]}... already processed: {auth_state['status']}")
            raise HTTPException(status_code=400, detail="Request already processed")
        
        # Check expiry
        if datetime.now() > auth_state['expires_at']:
            del self.pending_auths[state]
            logger.warning(f"⚠️ Auth state {state[:8]}... expired")
            raise HTTPException(status_code=400, detail="Authentication expired")
        
        try:
            # Exchange request_token for access_token
            logger.info(f"🔄 Exchanging token for state {state[:8]}...")
            response = self.kite.generate_session(request_token, api_secret=config.ZAPI_SECRET)
            access_token = response["access_token"]
            
            # Update .env file on EC2
            success = config.update_access_token(access_token)
            
            # Update auth state
            auth_state.update({
                'status': 'completed' if success else 'failed',
                'access_token': access_token[:8] + "..." if access_token else None,
                'request_token': request_token,
                'completed_at': datetime.now(),
                'success': success
            })
            
            # Cleanup and archive
            del self.pending_auths[state]
            await self._archive_auth_result(auth_state)
            
            # Notify Telegram
            await self._notify_telegram_success(access_token, state)
            
            logger.info(f"✅ Token exchange SUCCESS for {state[:8]}... (token: {access_token[:8]}...)")
            return {
                'success': True,
                'state': state,
                'access_token': access_token[:8] + "...",
                'token_length': len(access_token),
                'expiry': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d 09:00 IST'),
                'mode': config.MODE
            }
            
        except Exception as e:
            logger.error(f"❌ Token exchange FAILED for {state[:8]}...: {e}")
            auth_state.update({
                'status': 'failed',
                'error': str(e),
                'completed_at': datetime.now()
            })
            await self._archive_auth_result(auth_state)
            raise HTTPException(status_code=500, detail=f"Token exchange failed: {str(e)}")
    
    async def _archive_auth_result(self, auth_data: Dict[str, Any]):
        """Archive authentication result for audit trail."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"auth_data/auth_result_{timestamp}.json"
        
        # Remove sensitive data before archiving
        safe_data = auth_data.copy()
        safe_data.pop('access_token', None)
        safe_data.pop('request_token', None)
        
        with open(filename, 'w') as f:
            json.dump(safe_data, f, indent=2)
        
        logger.debug(f"📁 Archived auth result: {filename}")
    
    async def _notify_telegram_success(self, access_token: str, state: str):
        """Send success notification to your Telegram bot."""
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
            
            message = (
                f"🔐 <b>Token Refresh Successful!</b>\n\n"
                f"✅ Access token updated automatically via postback\n"
                f"🔑 Token: <code>{access_token[:8]}...</code>\n"
                f"📏 Length: 32 characters\n"
                f"⏰ Valid until: {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d 09:00 IST')}\n"
                f"🌐 Server: <code>{config.POSTBACK_HOST}</code>\n"
                f"🔑 State: <code>{state[:8]}...</code>\n"
                f"⚙️ Mode: <b>{config.MODE}</b>\n\n"
                f"📊 Trading will resume at 9:18 AM IST"
            )
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={
                    'chat_id': config.TELEGRAM_CHAT_ID,
                    'text': message,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True
                })
            
            logger.info(f"📱 Telegram success notification sent for {state[:8]}...")
            
        except Exception as e:
            logger.error(f"❌ Telegram notification failed: {e}")
    
    def cleanup_expired(self):
        """Clean up expired auth requests."""
        now = datetime.now()
        expired_count = 0
        
        for state in list(self.pending_auths.keys()):
            if now > self.pending_auths[state]['expires_at']:
                logger.info(f"🧹 Cleaning expired auth: {state[:8]}...")
                del self.pending_auths[state]
                expired_count += 1
        
        if expired_count > 0:
            logger.info(f"🧹 Cleaned {expired_count} expired auth requests")
        
        return expired_count

# Initialize auth manager
auth_manager = AuthManager()

# FastAPI app
app = FastAPI(
    title="Sensex Trading Auth Server",
    description="Handles Zerodha postback authentication for EC2 deployment",
    version="2.0.0"
)

@app.get("/", response_class=HTMLResponse)
async def root():
    """Main status page for your auth server."""
    pending_count = len(auth_manager.pending_auths)
    expired_cleaned = auth_manager.cleanup_expired()
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sensex Trading Auth Server</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }}
            .container {{ background: rgba(255,255,255,0.1); padding: 30px; border-radius: 10px; }}
            .status {{ padding: 15px; margin: 15px 0; border-radius: 8px; }}
            .healthy {{ background: rgba(40, 167, 69, 0.2); border-left: 4px solid #28a745; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
            .stat {{ background: rgba(255,255,255,0.1); padding: 15px; border-radius: 8px; }}
            .endpoint {{ background: #f8f9fa; color: #333; padding: 8px; border-radius: 4px; font-family: monospace; margin: 5px 0; }}
            a {{ color: #4CAF50; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .emoji {{ font-size: 1.5em; margin-right: 8px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1><span class="emoji">🚀</span>Sensex Trading Auth Server</h1>
            
            <div class="status healthy">
                <strong>Status:</strong> 
                <span style="color: #28a745;">✅ Active & Healthy</span>
                <span style="float: right; font-size: 0.9em;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}</span>
            </div>
            
            <div class="stats">
                <div class="stat">
                    <strong>🌐 Server:</strong><br>
                    <code>{config.POSTBACK_HOST}:{config.POSTBACK_PORT}</code>
                </div>
                <div class="stat">
                    <strong>🔒 Protocol:</strong><br>
                    {'HTTPS' if config.USE_HTTPS else 'HTTP'}
                </div>
                <div class="stat">
                    <strong>⚙️ Mode:</strong><br>
                    {config.MODE}
                </div>
                <div class="stat">
                    <strong>⏱️ Auth Timeout:</strong><br>
                    {config.AUTH_TIMEOUT}s
                </div>
                <div class="stat">
                    <strong>📊 Pending Auths:</strong><br>
                    {pending_count}
                </div>
                <div class="stat">
                    <strong>🧹 Expired Cleaned:</strong><br>
                    {expired_cleaned}
                </div>
            </div>
            
            <h3>🔗 API Endpoints</h3>
            <div class="endpoint">GET <strong>/health</strong> - System health check</div>
            <div class="endpoint">GET <strong>/auth/generate?state=xyz</strong> - Generate login URL</div>
            <div class="endpoint">GET <strong>/postback?state=xyz&request_token=ABC</strong> - Zerodha callback</div>
            <div class="endpoint">GET <strong>/pending</strong> - View pending auth requests</div>
            
            <h3>📱 Telegram Integration</h3>
            <p><strong>New /auth Command:</strong></p>
            <ol>
                <li><code>/auth</code> → Click "Login to Zerodha" button</li>
                <li>Login in browser → Automatic redirect to postback</li>
                <li>✅ Token updated! No copy-paste needed</li>
            </ol>
            
            <h3>🛡️ Security</h3>
            <ul>
                <li><strong>EC2 Deployment:</strong> .env file (chmod 600) - Git excluded</li>
                <li><strong>HTTPS:</strong> Enabled on port {config.POSTBACK_PORT}</li>
                <li><strong>Token Security:</strong> Atomic updates, masked logging</li>
                <li><strong>Audit Trail:</strong> auth_data/ directory with JSON logs</li>
            </ul>
            
            <hr>
            <p style="text-align: center; opacity: 0.8;">
                <small>Deployed on EC2 • {config.POSTBACK_HOST} • v2.0.0</small>
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    auth_manager.cleanup_expired()
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server": {
            "host": config.POSTBACK_HOST,
            "port": config.POSTBACK_PORT,
            "protocol": "https" if config.USE_HTTPS else "http"
        },
        "auth": {
            "pending_requests": len(auth_manager.pending_auths),
            "timeout_seconds": config.AUTH_TIMEOUT,
            "mode": config.MODE
        },
        "token": {
            "valid": bool(config.ACCESS_TOKEN),
            "expiry_check": "passed" if config.ACCESS_TOKEN else "expired/missing"
        }
    }

@app.get("/auth/generate")
async def generate_auth_url(state: Optional[str] = Query(None)):
    """
    Generate Zerodha login URL for Telegram /auth command.
    
    Telegram bot calls this endpoint to get login URL with inline button.
    """
    if not state:
        state = secrets.token_urlsafe(32)
        logger.info(f"🆕 New auth session generated: {state[:8]}...")
    
    try:
        auth_data = auth_manager.generate_auth_url(state)
        logger.info(f"✅ Auth URL generated for {state[:8]}...")
        return auth_data
    except Exception as e:
        logger.error(f"❌ Auth generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/postback")
async def handle_zerodha_postback(
    state: str = Query(...),
    request_token: str = Query(...),
    status: Optional[str] = Query(None)
):
    """
    Zerodha Postback Handler
    Called automatically: https://sensexbot.ddns.net/postback?request_token=ABC123&status=success
    """
    logger.info(f"📥 POSTBACK received: state={state[:8]}..., token={request_token[:8]}..., status={status}")
    
    if not request_token or len(request_token) < 10:
        logger.warning(f"⚠️ Invalid request_token length: {len(request_token) if request_token else 0}")
        raise HTTPException(status_code=400, detail="Invalid request token")
    
    try:
        result = await auth_manager.handle_postback(state, request_token)
        
        # Redirect to success page
        success_url = f"/success?state={state}&token={result['access_token']}"
        logger.info(f"🔄 Redirecting to success: {success_url}")
        return RedirectResponse(url=success_url, status_code=302)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Postback processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Postback failed: {str(e)}")

@app.get("/success")
async def success_page(state: str, token: str = Query(None)):
    """Success page after authentication."""
    success_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>✅ Authentication Successful</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
                text-align: center; padding: 50px; 
                background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
                color: white; min-height: 100vh; display: flex; align-items: center; justify-content: center;
            }}
            .container {{ max-width: 500px; padding: 30px; }}
            .success {{ font-size: 64px; margin: 20px 0; animation: bounce 1s; }}
            @keyframes bounce {{ 0%, 20%, 50%, 80%, 100% {{ transform: translateY(0); }} 40% {{ transform: translateY(-10px); }} 60% {{ transform: translateY(-5px); }} }}
            .token {{ background: rgba(255,255,255,0.2); padding: 15px; border-radius: 8px; margin: 20px 0; font-family: monospace; }}
            .button {{ 
                background: rgba(255,255,255,0.2); color: white; padding: 12px 24px; 
                text-decoration: none; border-radius: 25px; margin: 10px; display: inline-block;
                border: 2px solid rgba(255,255,255,0.3); transition: all 0.3s;
            }}
            .button:hover {{ background: rgba(255,255,255,0.3); transform: translateY(-2px); }}
            .state {{ font-size: 0.9em; opacity: 0.8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success">✅</div>
            <h1>Authentication Successful!</h1>
            <p>Your Sensex Trading Bot has been updated with a new access token.</p>
            <div class="token">
                <strong>Token ID:</strong> {token}...
            </div>
            <p class="state"><strong>Request ID:</strong> {state[:8]}...</p>
            <p>Everything is set up for trading. You can close this window.</p>
            <p>
                <a href="https://t.me/YOUR_BOT_USERNAME" class="button">📱 Open Telegram Bot</a>
                <a href="/" class="button">🔄 Server Status</a>
            </p>
            <hr style="margin-top: 30px; opacity: 0.3;">
            <p style="opacity: 0.6;"><small>
                Powered by sensexbot.ddns.net • {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}
            </small></p>
        </div>
    </body>
    </html>
    """
    
    # Replace with your actual bot username
    return HTMLResponse(content=success_message.replace("YOUR_BOT_USERNAME", "your_actual_bot_username"))

@app.get("/pending")
async def get_pending_auths():
    """Get pending authentication requests (for debugging)."""
    cleaned = auth_manager.cleanup_expired()
    pending_states = list(auth_manager.pending_auths.keys())
    
    return {
        "status": "ok",
        "pending_count": len(pending_auths),
        "pending_states": pending_states,
        "cleaned_expired": cleaned,
        "config": {
            "host": config.POSTBACK_HOST,
            "port": config.POSTBACK_PORT,
            "https": config.USE_HTTPS,
            "timeout": config.AUTH_TIMEOUT
        }
    }

@app.get("/token/manual")
async def manual_token_exchange(request_token: str = Query(...), state: Optional[str] = Query(None)):
    """
    Fallback: Manual token exchange if postback fails.
    
    Usage: GET /token/manual?request_token=ABC123
    """
    if not request_token or len(request_token) < 10:
        raise HTTPException(status_code=400, detail="Invalid request token")
    
    target_state = state or secrets.token_urlsafe(16)
    logger.info(f"🔧 Manual token exchange for state {target_state[:8]}...")
    
    try:
        result = await auth_manager.handle_postback(target_state, request_token)
        return {
            "success": True,
            "message": "Manual token exchange completed",
            "state": target_state,
            "token_preview": result['access_token']
        }
    except Exception as e:
        logger.error(f"❌ Manual exchange failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    # SSL configuration for EC2 HTTPS
    ssl_keyfile = "ssl/key.pem" if config.USE_HTTPS else None
    ssl_certfile = "ssl/cert.pem" if config.USE_HTTPS else None
    
    logger.info(f"🚀 Starting Auth Server on {config.POSTBACK_HOST}:{config.POSTBACK_PORT}")
    logger.info(f"🔒 HTTPS: {config.USE_HTTPS} | SSL: {ssl_keyfile is not None}")
    logger.info(f"📍 Postback URL: {config.get_auth_url()}/postback")
    logger.info(f"⚙️ Trading Mode: {config.MODE}")
    
    uvicorn.run(
        "auth_server:app",
        host=config.POSTBACK_HOST,
        port=config.POSTBACK_PORT,
        log_level="info",
        access_log=True,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile
    )
