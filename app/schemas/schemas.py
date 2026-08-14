from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

# --- Auth & User Schemas ---
class UserSignUp(BaseModel):
    fullName: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class OTPVerify(BaseModel):
    email: EmailStr
    otpCode: str

class OnboardingStep1(BaseModel):
    fullName: str
    phone: str
    jobTitle: str

class OnboardingStep2(BaseModel):
    companyName: str
    companyWebsite: Optional[str] = None
    targetIndustry: str

class OnboardingStep3(BaseModel):
    targetCities: List[str]
    targetBusinessTypes: List[str]

class UserProfileUpdate(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    jobTitle: Optional[str] = None

# --- Lead Discovery & Business Schemas ---
class MapsSearchRequest(BaseModel):
    keyword: str
    location: str
    radiusKm: int = 10
    minRating: Optional[float] = 0.0
    minReviews: Optional[int] = 0
    hasWebsite: bool = False
    verifiedEmail: bool = False

class BusinessSchema(BaseModel):
    id: Optional[str] = None
    userId: str
    name: str
    category: str
    address: str
    phone: Optional[str] = None
    website: Optional[str] = None
    rating: float = 0.0
    reviewCount: int = 0
    placeId: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    openingHours: Optional[List[str]] = []
    emails: Optional[List[Dict[str, Any]]] = []
    owner: Optional[str] = None
    socialLinks: Optional[Dict[str, str]] = {}
    websiteIntelligence: Optional[Dict[str, Any]] = {}
    aiScore: Optional[int] = 0
    intent: Optional[str] = "UNSCORED"
    reasoning: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)

# --- CRM Pipeline & Lead Schemas ---
class LeadPipelineUpdate(BaseModel):
    leadId: str
    stage: str
    notes: Optional[str] = None
    nextFollowUpAt: Optional[str] = None

class ColdPitchRequest(BaseModel):
    businessId: str
    pitchType: str  # Website Redesign, Local SEO, Review Growth, Digital Marketing, Chatbot
    customInstructions: Optional[str] = None

# --- Integration & Config Schemas ---
class IntegrationConfigUpdate(BaseModel):
    googlePlacesApiKey: Optional[str] = None
    serperApiKey: Optional[str] = None
    aiProvider: Optional[str] = "groq"  # groq or ollama
    smtpHost: Optional[str] = None
    smtpPort: Optional[int] = None
    smtpUsername: Optional[str] = None
    smtpPassword: Optional[str] = None
    imapHost: Optional[str] = None
    imapPort: Optional[int] = None
    imapUsername: Optional[str] = None
    imapPassword: Optional[str] = None
