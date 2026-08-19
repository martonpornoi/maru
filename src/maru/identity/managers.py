"""Managers for the platform account."""

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:
    from maru.identity.models import Account


class AccountManager(BaseUserManager["Account"]):
    """Describe account manager."""

    use_in_migrations = True

    @staticmethod
    def normalize_login_email(email: str) -> str:
        """Normalize login email.

        Parameters
        ----------
        email : str
            The normalized email address used for delivery or identity matching.

        Returns
        -------
        str
            The normalized text for normalize login email.
        """
        normalized = BaseUserManager.normalize_email(email).strip()
        return normalized.casefold()

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> "Account":
        """Create user.

        Parameters
        ----------
        email : str
            The normalized email address used for delivery or identity matching.
        password : str | None, default=None
            The plaintext secret to verify without logging or retaining it.
        **extra_fields : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        Account
            The newly created Account.

        Raises
        ------
        ValueError
            If the supplied value cannot satisfy the documented contract.
        """
        if not email:
            raise ValueError("An email address is required")
        account = self.model(
            email=self.normalize_login_email(email),
            **extra_fields,
        )
        account.set_password(password)
        account.full_clean()
        account.save(using=self._db)
        return account

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> "Account":
        """Create superuser.

        Parameters
        ----------
        email : str
            The normalized email address used for delivery or identity matching.
        password : str | None, default=None
            The plaintext secret to verify without logging or retaining it.
        **extra_fields : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        Account
            The newly created Account.

        Raises
        ------
        ValueError
            If the supplied value cannot satisfy the documented contract.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("account_kind", "platform_administrator")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True")
        if extra_fields.get("account_kind") != "platform_administrator":
            raise ValueError("A superuser must be a platform administrator")
        return self.create_user(email, password, **extra_fields)
