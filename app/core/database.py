import json
import os
import logging
from typing import Dict, Any, List, Optional
from pymongo import MongoClient
from app.core.config import settings

logger = logging.getLogger("mapflow_ai.database")

class JSONFallbackDB:
    def __init__(self, data_dir: str = "data_storage"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_file = os.path.join(self.data_dir, "database.json")
        self.login_file = os.path.join(self.data_dir, "login.json")
        self._init_files()

    def _init_files(self):
        if not os.path.exists(self.db_file):
            with open(self.db_file, "w") as f:
                json.dump({
                    "users": [],
                    "subscriptions": [],
                    "credit_transactions": [],
                    "businesses": [],
                    "leads": [],
                    "map_scans": [],
                    "scan_schedules": [],
                    "outreach_activities": [],
                    "ai_usage": [],
                    "integrations": [],
                    "webhooks": [],
                    "pricing_plans": []
                }, f, indent=2)
        if not os.path.exists(self.login_file):
            with open(self.login_file, "w") as f:
                json.dump([], f, indent=2)

    def _read_db(self) -> Dict[str, Any]:
        try:
            with open(self.db_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading JSON DB: {e}")
            return {}

    def _write_db(self, data: Dict[str, Any]):
        try:
            with open(self.db_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error writing to JSON DB: {e}")

    def find_one(self, collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        db = self._read_db()
        items = db.get(collection, [])
        for item in items:
            match = True
            for k, v in query.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                return item
        return None

    def find(self, collection: str, query: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        db = self._read_db()
        items = db.get(collection, [])
        if not query:
            return items
        results = []
        for item in items:
            match = True
            for k, v in query.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                results.append(item)
        return results

    def insert_one(self, collection: str, document: Dict[str, Any]) -> Dict[str, Any]:
        db = self._read_db()
        if collection not in db:
            db[collection] = []
        db[collection].append(document)
        self._write_db(db)
        return document

    def update_one(self, collection: str, query: Dict[str, Any], update: Dict[str, Any]) -> bool:
        db = self._read_db()
        items = db.get(collection, [])
        for idx, item in enumerate(items):
            match = True
            for k, v in query.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                if "$set" in update:
                    items[idx].update(update["$set"])
                else:
                    items[idx].update(update)
                db[collection] = items
                self._write_db(db)
                return True
        return False

    def delete_one(self, collection: str, query: Dict[str, Any]) -> bool:
        db = self._read_db()
        items = db.get(collection, [])
        for idx, item in enumerate(items):
            match = True
            for k, v in query.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                del items[idx]
                db[collection] = items
                self._write_db(db)
                return True
        return False

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.use_json_fallback = False
        self.json_db = JSONFallbackDB()

    def connect(self):
        try:
            self.client = MongoClient(
                settings.MONGODB_URI,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
                socketTimeoutMS=3000,
                connect=False
            )
            self.client.server_info()  # Ping MongoDB

            self.db = self.client[settings.DATABASE_NAME]
            self.use_json_fallback = False
            logger.info(f"Successfully connected to MongoDB ({settings.DATABASE_NAME}).")
        except Exception as e:
            if settings.JSON_DB_FALLBACK:
                logger.warning(f"MongoDB connection failed: {e}. Activating JSON file DB fallback mode.")
                self.use_json_fallback = True
            else:
                logger.error(f"Failed to connect to MongoDB at {settings.MONGODB_URI}: {e}")
                raise RuntimeError(f"MongoDB connection error: {e}. Please ensure MongoDB is running.")

    def get_collection(self, collection_name: str):
        if self.db is None:
            self.connect()
        if self.db is not None:
            return self.db[collection_name]
        if self.use_json_fallback:
            return None
        raise RuntimeError("MongoDB connection not initialized.")



db_manager = DatabaseManager()
