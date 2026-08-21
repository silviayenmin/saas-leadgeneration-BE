import smtplib
import logging
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger("mapflow_ai.email_service")

class EmailService:
    @staticmethod
    def send_otp_email(to_email: str, otp_code: str) -> bool:
        """
        Sends an HTML formatted OTP verification email via SMTP with timeout & error handling.
        """
        smtp_user = settings.SMTP_USERNAME.strip()
        smtp_pass = settings.SMTP_PASSWORD.strip().replace(" ", "")

        # Check if dummy placeholder or empty credentials
        if not smtp_user or not smtp_pass or "your-actual-email" in smtp_user or "your-email" in smtp_user:
            logger.info(f"[SIMULATED EMAIL] OTP Code for '{to_email}' is: {otp_code} (Configure valid SMTP_USERNAME & SMTP_PASSWORD in .env for live delivery)")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"MapFlow AI — {otp_code} is your Email Verification Code"
            msg["From"] = f"MapFlow AI <{smtp_user}>"
            msg["To"] = to_email

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <style>
                body {{ font-family: 'Inter', Arial, sans-serif; background-color: #0A0F1C; color: #F8FAFC; padding: 20px; }}
                .card {{ max-width: 480px; margin: 0 auto; background: #182233; border: 1px solid rgba(148,163,184,0.15); border-radius: 12px; padding: 32px; text-align: center; }}
                .code {{ font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0EA5A4; margin: 24px 0; background: #111827; padding: 16px; border-radius: 8px; display: inline-block; }}
                .footer {{ font-size: 12px; color: #94A3B8; margin-top: 24px; }}
              </style>
            </head>
            <body>
              <div class="card">
                <h2 style="color: #0EA5A4;">MAPFLOW AI</h2>
                <h3 style="color: #F8FAFC;">Verify Your Email Address</h3>
                <p style="color: #94A3B8;">Thank you for registering with MapFlow AI. Please use the verification code below to complete your setup:</p>
                <div class="code">{otp_code}</div>
                <p style="color: #94A3B8; font-size: 13px;">This code is valid for 10 minutes. If you did not request this code, please ignore this email.</p>
                <div class="footer">© 2026 MapFlow AI. All rights reserved.</div>
              </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_content, "html"))

            # 5-second socket timeout to prevent blocking/hanging
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())

            logger.info(f"Successfully delivered OTP email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send OTP email to {to_email}: {e}")
            return False

    @staticmethod
    def send_async_otp_email(to_email: str, otp_code: str):
        """Spawns an un-blocked daemon thread to deliver the email without delaying API responses."""
        thread = threading.Thread(
            target=EmailService.send_otp_email,
            args=(to_email, otp_code),
            daemon=True
        )
        thread.start()

    @staticmethod
    def send_reset_password_email(to_email: str, reset_code: str) -> bool:
        """
        Sends an HTML formatted password reset verification code email via SMTP with timeout & error handling.
        """
        smtp_user = settings.SMTP_USERNAME.strip()
        smtp_pass = settings.SMTP_PASSWORD.strip().replace(" ", "")

        if not smtp_user or not smtp_pass or "your-actual-email" in smtp_user or "your-email" in smtp_user:
            logger.info(f"[SIMULATED EMAIL] Password Reset Code for '{to_email}' is: {reset_code} (Configure valid SMTP_USERNAME & SMTP_PASSWORD in .env for live delivery)")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"MapFlow AI — {reset_code} is your Password Reset Code"
            msg["From"] = f"MapFlow AI <{smtp_user}>"
            msg["To"] = to_email

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <style>
                body {{ font-family: 'Inter', Arial, sans-serif; background-color: #0A0F1C; color: #F8FAFC; padding: 20px; }}
                .card {{ max-width: 480px; margin: 0 auto; background: #182233; border: 1px solid rgba(148,163,184,0.15); border-radius: 12px; padding: 32px; text-align: center; }}
                .code {{ font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0EA5A4; margin: 24px 0; background: #111827; padding: 16px; border-radius: 8px; display: inline-block; }}
                .footer {{ font-size: 12px; color: #94A3B8; margin-top: 24px; }}
              </style>
            </head>
            <body>
              <div class="card">
                <h2 style="color: #0EA5A4;">MAPFLOW AI</h2>
                <h3 style="color: #F8FAFC;">Reset Your Password</h3>
                <p style="color: #94A3B8;">We received a request to reset your password. Use the verification code below to set a new password:</p>
                <div class="code">{reset_code}</div>
                <p style="color: #94A3B8; font-size: 13px;">This code is valid for 10 minutes. If you did not request a password reset, please ignore this email.</p>
                <div class="footer">© 2026 MapFlow AI. All rights reserved.</div>
              </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())

            logger.info(f"Successfully delivered password reset email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send password reset email to {to_email}: {e}")
            return False

    @staticmethod
    def send_async_reset_password_email(to_email: str, reset_code: str):
        """Spawns an un-blocked daemon thread to deliver the reset email."""
        thread = threading.Thread(
            target=EmailService.send_reset_password_email,
            args=(to_email, reset_code),
            daemon=True
        )
        thread.start()

    @staticmethod
    def send_admin_credentials_email(to_email: str, name: str, role: str, password: str) -> bool:
        """
        Sends an HTML formatted admin account creation email containing the random password via SMTP.
        """
        smtp_user = settings.SMTP_USERNAME.strip()
        smtp_pass = settings.SMTP_PASSWORD.strip().replace(" ", "")

        if not smtp_user or not smtp_pass or "your-actual-email" in smtp_user or "your-email" in smtp_user:
            logger.info(f"[SIMULATED EMAIL] Admin Credentials for '{to_email}' name: {name}, role: {role}, password: {password} (Configure valid SMTP_USERNAME & SMTP_PASSWORD in .env for live delivery)")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "MapFlow AI — Your Admin Account Has Been Created"
            msg["From"] = f"MapFlow AI <{smtp_user}>"
            msg["To"] = to_email

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <style>
                body {{ font-family: 'Inter', Arial, sans-serif; background-color: #0A0F1C; color: #F8FAFC; padding: 20px; }}
                .card {{ max-width: 480px; margin: 0 auto; background: #182233; border: 1px solid rgba(148,163,184,0.15); border-radius: 12px; padding: 32px; text-align: left; }}
                .credentials {{ font-family: monospace; background: #111827; padding: 16px; border-radius: 8px; color: #0EA5A4; margin: 20px 0; font-size: 14px; line-height: 1.6; }}
                .footer {{ font-size: 12px; color: #94A3B8; margin-top: 24px; text-align: center; }}
              </style>
            </head>
            <body>
              <div class="card">
                <h2 style="color: #0EA5A4; text-align: center; margin-bottom: 24px;">MAPFLOW AI</h2>
                <h3 style="color: #F8FAFC;">Welcome to the Team, {name}!</h3>
                <p style="color: #94A3B8;">An administrative account has been created for you on the MapFlow AI Admin Console.</p>
                <p style="color: #94A3B8;">Below are your temporary credentials. Please log in and change your password immediately.</p>
                
                <div class="credentials">
                  <strong>Role:</strong> {role}<br/>
                  <strong>Email:</strong> {to_email}<br/>
                  <strong>Temporary Password:</strong> {password}
                </div>
                
                <div class="footer">© 2026 MapFlow AI. All rights reserved.</div>
              </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())

            logger.info(f"Successfully delivered admin credentials email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send admin credentials email to {to_email}: {e}")
            return False

    @staticmethod
    def send_async_admin_credentials_email(to_email: str, name: str, role: str, password: str):
        """Spawns an un-blocked daemon thread to deliver the email."""
        thread = threading.Thread(
            target=EmailService.send_admin_credentials_email,
            args=(to_email, name, role, password),
            daemon=True
        )
        thread.start()

