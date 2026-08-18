from .linkedin_adapter import LinkedInAdapter
from .facebook_adapter import FacebookAdapter
from .twitter_adapter import TwitterAdapter
from .reddit_adapter import RedditAdapter
from .google_maps_adapter import GoogleMapsAdapter
from .weworkremotely_adapter import WeWorkRemotelyAdapter
from .freelancer_adapter import FreelancerAdapter
from .upwork_adapter import UpworkAdapter
from .query_generator import IntentQueryGenerator

def get_adapter(platform: str):
    platform = platform.lower().strip()
    if platform == "linkedin":
        return LinkedInAdapter()
    elif platform == "facebook":
        return FacebookAdapter()
    elif platform in ["twitter", "x", "twitter/x"]:
        return TwitterAdapter()
    elif platform == "reddit":
        return RedditAdapter()
    elif platform == "google_maps":
        return GoogleMapsAdapter()
    elif platform == "weworkremotely":
        return WeWorkRemotelyAdapter()
    elif platform == "freelancer":
        return FreelancerAdapter()
    elif platform == "upwork":
        return UpworkAdapter()
    else:
        # If "all", we return a generic runner or fallback
        return LinkedInAdapter()
