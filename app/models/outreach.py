import uuid
import datetime
import enum
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Enum as SqlEnum, JSON
from app.core.outreach_db import Base

class EncryptionType(str, enum.Enum):
    SSL = "SSL"
    TLS = "TLS"
    STARTTLS = "STARTTLS"
    NONE = "NONE"

class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True)
    sender_name = Column(String(100), nullable=False)
    email_address = Column(String(150), unique=True, nullable=False)
    
    smtp_host = Column(String(200), nullable=False)
    smtp_port = Column(Integer, nullable=False)
    smtp_username = Column(String(150), nullable=False)
    smtp_password_encrypted = Column(String(500), nullable=False)
    smtp_encryption = Column(String(50), default="SSL") # SSL, TLS, STARTTLS, NONE
    
    imap_host = Column(String(200), nullable=False)
    imap_port = Column(Integer, nullable=False)
    imap_username = Column(String(150), nullable=False)
    imap_password_encrypted = Column(String(500), nullable=False)
    imap_ssl = Column(Boolean, default=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class OutreachSettings(Base):
    __tablename__ = "outreach_settings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), unique=True, nullable=False, index=True)
    
    timezone = Column(String(100), default="UTC")
    active_days = Column(JSON, default=list) # ["Monday", "Tuesday", ...]
    
    max_emails_per_day = Column(Integer, default=50)
    min_delay_seconds = Column(Integer, default=60)
    max_delay_seconds = Column(Integer, default=180)
    
    signature_html = Column(Text, default="")
    
    enable_warmup = Column(Boolean, default=False)
    warmup_start_count = Column(Integer, default=10)
    warmup_daily_increase = Column(Integer, default=2)
    warmup_max_count = Column(Integer, default=50)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
