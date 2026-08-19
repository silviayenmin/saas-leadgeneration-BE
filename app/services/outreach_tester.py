import smtplib
import imaplib
import socket
import ssl

def test_smtp_connection(host: str, port: int, username: str, password: str, encryption: str) -> dict:
    encryption = str(encryption).upper().strip()
    try:
        if encryption == "SSL":
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(host, port, timeout=10, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            
        server.ehlo()
        
        if encryption in ["STARTTLS", "TLS"]:
            context = ssl.create_default_context()
            server.starttls(context=context)
            server.ehlo()
            
        if username and password:
            server.login(username, password)
            
        server.quit()
        return {"status": "success", "message": "SMTP connection tested successfully!"}
    except socket.timeout:
        return {"status": "error", "message": "SMTP connection timed out (server took too long to respond)."}
    except socket.gaierror:
        return {"status": "error", "message": "SMTP connection failed: Hostname resolution error (invalid host name)."}
    except smtplib.SMTPAuthenticationError:
        return {"status": "error", "message": "SMTP authentication failed: Invalid username or password."}
    except Exception as e:
        return {"status": "error", "message": f"SMTP error: {str(e)}"}

def test_imap_connection(host: str, port: int, username: str, password: str, use_ssl: bool) -> dict:
    try:
        if use_ssl:
            context = ssl.create_default_context()
            server = imaplib.IMAP4_SSL(host, port, timeout=10, ssl_context=context)
        else:
            server = imaplib.IMAP4(host, port, timeout=10)
            
        if username and password:
            server.login(username, password)
            
        server.logout()
        return {"status": "success", "message": "IMAP connection tested successfully!"}
    except socket.timeout:
        return {"status": "error", "message": "IMAP connection timed out (server took too long to respond)."}
    except socket.gaierror:
        return {"status": "error", "message": "IMAP connection failed: Hostname resolution error (invalid host name)."}
    except imaplib.IMAP4.error as e:
        return {"status": "error", "message": f"IMAP authentication failed: {str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"IMAP error: {str(e)}"}
