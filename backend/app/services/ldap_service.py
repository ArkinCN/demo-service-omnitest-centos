"""
LDAP authentication service
"""
from typing import Optional, Dict
from ldap3 import Server, Connection, ALL, NTLM
from ldap3.core.exceptions import LDAPException

from app.core.config import settings
from app.core.logger import logger


class LDAPService:
    """LDAP authentication service"""

    @staticmethod
    def authenticate(username: str, password: str) -> Optional[Dict[str, str]]:
        """
        Authenticate user against LDAP server

        Args:
            username: LDAP username
            password: User password

        Returns:
            User information dict if authenticated, None otherwise
            Dict contains: username, displayName, mail

        Raises:
            Exception: If LDAP connection fails
        """
        try:
            # Create LDAP server
            server = Server(settings.LDAP_URL, get_info=ALL)

            # Connect as admin to search for user
            admin_conn = Connection(
                server,
                user=settings.LDAP_ADMIN_DN,
                password=settings.LDAP_ADMIN_PASSWORD,
                auto_bind=True
            )

            # Search for user
            search_filter = f"(uid={username})"
            admin_conn.search(
                search_base=settings.LDAP_SEARCH_BASE,
                search_filter=search_filter,
                attributes=["uid", "displayName", "mail"]
            )

            if not admin_conn.entries:
                logger.warning(f"LDAP user not found: {username}")
                return None

            # Get user DN and attributes
            user_entry = admin_conn.entries[0]
            user_dn = user_entry.entry_dn
            display_name = str(user_entry.displayName) if hasattr(user_entry, 'displayName') else username
            email = str(user_entry.mail) if hasattr(user_entry, 'mail') else f"{username}@example.com"

            admin_conn.unbind()

            # Try to bind as the user to verify password
            user_conn = Connection(
                server,
                user=user_dn,
                password=password,
                auto_bind=True
            )

            if user_conn.bound:
                user_conn.unbind()
                logger.info(f"LDAP authentication successful for user: {username}")

                return {
                    "username": username,
                    "displayName": display_name,
                    "mail": email
                }
            else:
                logger.warning(f"LDAP authentication failed for user: {username}")
                return None

        except LDAPException as e:
            logger.error(f"LDAP error during authentication: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during LDAP authentication: {str(e)}")
            return None

    @staticmethod
    def test_connection() -> bool:
        """
        Test LDAP server connection

        Returns:
            True if connection successful, False otherwise
        """
        try:
            server = Server(settings.LDAP_URL, get_info=ALL)
            conn = Connection(
                server,
                user=settings.LDAP_ADMIN_DN,
                password=settings.LDAP_ADMIN_PASSWORD,
                auto_bind=True
            )

            if conn.bound:
                conn.unbind()
                logger.info("LDAP connection test successful")
                return True
            else:
                logger.warning("LDAP connection test failed")
                return False

        except Exception as e:
            logger.error(f"LDAP connection test error: {str(e)}")
            return False
