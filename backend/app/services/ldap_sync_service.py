"""
LDAP Synchronization Service

Handles periodic synchronization of users and groups from LDAP server.
- Syncs users based on their DN
- Creates/updates LDAP groups based on OU hierarchy
- Auto-creates new users from LDAP
- Auto-disables users removed from LDAP
"""
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException
from sqlmodel import Session, select, func

from app.models.user import User
from app.models.user_group import UserGroup, UserGroupMember
from app.services.user_group_service import UserGroupService
from app.core.config import settings
from app.core.logger import logger


class LdapSyncService:
    """LDAP synchronization service"""

    # Class-level sync status
    _is_running: bool = False
    _last_sync_at: Optional[datetime] = None
    _last_sync_status: Optional[str] = None
    _last_sync_message: Optional[str] = None
    _last_sync_result: Optional[dict] = None

    @classmethod
    def is_running(cls) -> bool:
        """Check if sync is currently running"""
        return cls._is_running

    @classmethod
    def get_status(cls) -> dict:
        """Get current sync status"""
        return {
            "is_running": cls._is_running,
            "last_sync_at": cls._last_sync_at,
            "last_sync_status": cls._last_sync_status,
            "last_sync_message": cls._last_sync_message,
            "last_sync_result": cls._last_sync_result
        }

    @staticmethod
    def parse_dn_ou_chain(dn: str) -> List[Tuple[str, str]]:
        """
        Parse DN string to extract OU chain from bottom to top

        Args:
            dn: Full DN string, e.g., "uid=dev1,ou=标准化部,ou=应用中心,ou=示例科技,dc=example,dc=internal"

        Returns:
            List of (ou_name, ou_dn) tuples from most specific to least specific
            Example: [
                ("标准化部", "ou=标准化部,ou=应用中心,ou=示例科技,dc=example,dc=internal"),
                ("应用中心", "ou=应用中心,ou=示例科技,dc=example,dc=internal"),
                ("示例科技", "ou=示例科技,dc=example,dc=internal")
            ]
        """
        ou_chain = []

        # Split DN into parts
        parts = dn.split(",")

        # Find all OU parts
        ou_indices = []
        for i, part in enumerate(parts):
            if part.strip().lower().startswith("ou="):
                ou_indices.append(i)

        # Build OU chain with their DNs
        for idx in ou_indices:
            ou_part = parts[idx].strip()
            ou_name = ou_part.split("=", 1)[1]  # Get value after "ou="
            ou_dn = ",".join(parts[idx:])  # DN from this OU onwards
            ou_chain.append((ou_name, ou_dn))

        return ou_chain

    @staticmethod
    def get_all_ldap_users() -> List[Dict]:
        """
        Fetch all users from LDAP server

        Returns:
            List of user dicts with uid, displayName, mail, dn
        """
        try:
            server = Server(settings.LDAP_URL, get_info=ALL)
            conn = Connection(
                server,
                user=settings.LDAP_ADMIN_DN,
                password=settings.LDAP_ADMIN_PASSWORD,
                auto_bind=True
            )

            # Search for all users
            conn.search(
                search_base=settings.LDAP_SEARCH_BASE,
                search_filter="(objectClass=person)",
                search_scope=SUBTREE,
                attributes=["uid", "displayName", "mail", "sn", "cn"]
            )

            users = []
            for entry in conn.entries:
                # Skip entries without uid
                if not hasattr(entry, 'uid') or not entry.uid.value:
                    continue

                user = {
                    "uid": str(entry.uid.value),
                    "dn": entry.entry_dn,
                    "displayName": str(entry.displayName.value) if hasattr(entry, 'displayName') and entry.displayName.value else None,
                    "mail": str(entry.mail.value) if hasattr(entry, 'mail') and entry.mail.value else None,
                    "cn": str(entry.cn.value) if hasattr(entry, 'cn') and entry.cn.value else None,
                }

                # Use cn as fallback for displayName
                if not user["displayName"]:
                    user["displayName"] = user["cn"] or user["uid"]

                # Generate default email if not present
                if not user["mail"]:
                    user["mail"] = f"{user['uid']}@example.internal"

                users.append(user)

            conn.unbind()
            logger.info(f"Fetched {len(users)} users from LDAP")
            return users

        except LDAPException as e:
            logger.error(f"LDAP error fetching users: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error fetching LDAP users: {str(e)}")
            raise

    @classmethod
    def sync(cls, session: Session, force: bool = False) -> dict:
        """
        Perform LDAP synchronization

        Args:
            session: Database session
            force: Force sync even if already running

        Returns:
            Sync result dict
        """
        if cls._is_running and not force:
            return {
                "status": "SKIPPED",
                "message": "Sync already in progress"
            }

        cls._is_running = True
        started_at = datetime.now(timezone.utc)

        result = {
            "status": "SUCCESS",
            "message": "",
            "users_created": 0,
            "users_updated": 0,
            "users_disabled": 0,
            "groups_synced": 0,
            "started_at": started_at,
            "completed_at": None,
            "errors": []
        }

        try:
            logger.info("Starting LDAP sync...")

            # Step 1: Fetch all LDAP users
            ldap_users = cls.get_all_ldap_users()
            ldap_usernames = set()
            processed_usernames = set()  # Track processed users to avoid duplicates

            # Step 2: Process each LDAP user
            for ldap_user in ldap_users:
                username = ldap_user.get("uid", "unknown").strip()  # Strip whitespace
                # Add to set outside try block to ensure it's always recorded
                # This prevents users from being incorrectly disabled
                if username != "unknown":
                    ldap_usernames.add(username.lower())  # Case-insensitive comparison

                # Skip if already processed (same uid in multiple OUs)
                if username.lower() in processed_usernames:
                    logger.debug(f"Skipping duplicate LDAP user: {username} (dn: {ldap_user.get('dn', 'unknown')})")
                    continue
                processed_usernames.add(username.lower())

                try:
                    # Use savepoint context manager for proper partial rollback
                    # This ensures savepoint is properly committed on success
                    # and rolled back on failure without affecting other users
                    with session.begin_nested():
                        dn = ldap_user["dn"]

                        # Parse OU chain from DN
                        ou_chain = cls.parse_dn_ou_chain(dn)

                        # Ensure LDAP groups exist (create from top to bottom)
                        group_ids = cls._ensure_ldap_group_hierarchy(session, ou_chain)

                        # Find or create user
                        user = cls._get_or_create_user(session, ldap_user, result)

                        # Update user's LDAP groups
                        if user and group_ids:
                            UserGroupService.update_user_ldap_groups(session, user.id, group_ids)

                except Exception as e:
                    # Savepoint is automatically rolled back by context manager
                    error_msg = f"Error processing user {username}: {str(e)}"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)
                    # Continue processing other users

            # Step 3: Disable users no longer in LDAP
            cls._disable_removed_users(session, ldap_usernames, result)

            # Commit all changes
            session.commit()

            result["status"] = "SUCCESS"
            result["message"] = f"Synced {len(ldap_users)} LDAP users"
            logger.info(f"LDAP sync completed: {result['message']}")

        except Exception as e:
            session.rollback()
            result["status"] = "FAILED"
            result["message"] = str(e)
            result["errors"].append(str(e))
            logger.error(f"LDAP sync failed: {str(e)}")

        finally:
            cls._is_running = False
            result["completed_at"] = datetime.now(timezone.utc)

            # Update class-level status
            cls._last_sync_at = started_at
            cls._last_sync_status = result["status"]
            cls._last_sync_message = result["message"]
            cls._last_sync_result = result

        return result

    @classmethod
    def _ensure_ldap_group_hierarchy(
        cls,
        session: Session,
        ou_chain: List[Tuple[str, str]]
    ) -> List[int]:
        """
        Ensure LDAP group hierarchy exists, creating groups as needed

        Args:
            session: Database session
            ou_chain: List of (ou_name, ou_dn) from bottom to top

        Returns:
            List of group IDs (from most specific to root)
        """
        if not ou_chain:
            return []

        # Process from top (root) to bottom (most specific)
        reversed_chain = list(reversed(ou_chain))
        group_ids = []
        parent_id = None

        for ou_name, ou_dn in reversed_chain:
            group = UserGroupService.get_or_create_ldap_group(
                session,
                name=ou_name,
                ldap_dn=ou_dn,
                parent_id=parent_id
            )
            group_ids.append(group.id)
            parent_id = group.id

        # Return in original order (specific to general)
        return list(reversed(group_ids))

    @classmethod
    def _get_or_create_user(
        cls,
        session: Session,
        ldap_user: Dict,
        result: dict
    ) -> Optional[User]:
        """
        Get or create a user from LDAP data

        Args:
            session: Database session
            ldap_user: LDAP user data dict
            result: Sync result dict to update

        Returns:
            User object or None
        """
        username = ldap_user["uid"].strip()

        # Find existing user by username (case-insensitive, trim whitespace)
        statement = select(User).where(
            func.lower(func.trim(User.username)) == username.lower()
        )
        user = session.exec(statement).first()

        if user:
            # Update existing user
            updated = False

            # Fix username if it has trailing/leading whitespace
            if user.username != user.username.strip():
                user.username = user.username.strip()
                updated = True

            if user.ldap_dn != ldap_user["dn"]:
                user.ldap_dn = ldap_user["dn"]
                updated = True

            if ldap_user["displayName"] and user.nickname != ldap_user["displayName"]:
                user.nickname = ldap_user["displayName"]
                updated = True

            if ldap_user["mail"] and user.email != ldap_user["mail"]:
                # Check email uniqueness
                email_check = select(User).where(
                    User.email == ldap_user["mail"],
                    User.id != user.id
                )
                if not session.exec(email_check).first():
                    user.email = ldap_user["mail"]
                    updated = True

            # Re-enable if was disabled
            if not user.is_active:
                user.is_active = True
                updated = True

            if updated:
                user.updated_at = datetime.now(timezone.utc)
                session.add(user)
                result["users_updated"] += 1
                logger.debug(f"Updated LDAP user: {username} (dn: {ldap_user['dn']})")

        else:
            # Create new user
            user = User(
                username=username,
                email=ldap_user["mail"],
                nickname=ldap_user["displayName"],
                auth_type="LDAP",
                ldap_dn=ldap_user["dn"],
                role="user",
                is_active=True
            )
            session.add(user)
            session.flush()  # Get ID
            result["users_created"] += 1
            logger.info(f"Created LDAP user: {username}")

        return user

    @classmethod
    def _disable_removed_users(
        cls,
        session: Session,
        ldap_usernames: set,
        result: dict
    ) -> None:
        """
        Disable users that are no longer in LDAP

        Args:
            session: Database session
            ldap_usernames: Set of usernames currently in LDAP
            result: Sync result dict to update
        """
        # Find all LDAP users in database
        statement = select(User).where(
            User.auth_type == "LDAP",
            User.is_active == True
        )
        db_ldap_users = session.exec(statement).all()

        for user in db_ldap_users:
            # Strip whitespace for comparison to handle usernames with trailing spaces
            if user.username.strip().lower() not in ldap_usernames:
                user.is_active = False
                user.updated_at = datetime.now(timezone.utc)
                session.add(user)
                result["users_disabled"] += 1
                logger.info(f"Disabled LDAP user (removed from LDAP): {user.username}")
