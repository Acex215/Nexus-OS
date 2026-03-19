"""Phase 3 — Risk-based approval gates, scope enforcement, and retry policy.

Classes:
    SafetyGate     — approve/reject tasks by risk level with human override support
    ScopeEnforcer  — verify file edits fall within a declared scope
    RetryPolicy    — retry failed executions with context-aware prompting
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from safety_config import AUTO_APPROVE_LOW, HIGH_RISK_TIMEOUT, MAX_RETRIES, MEDIUM_RISK_TIMEOUT

if TYPE_CHECKING:
    import discord

logger = logging.getLogger("safety_gates")

# ---------------------------------------------------------------------------
# Risk keyword sets
# ---------------------------------------------------------------------------

_HIGH_KEYWORDS = {
    "deploy", "contract", "blockchain", "delete", "remove",
    "migration", "production", ".env", "keystore", "password",
}
_MEDIUM_KEYWORDS = {
    "refactor", "rewrite", "restructure", "security", "rename", "move",
}


# ---------------------------------------------------------------------------
# SafetyGate
# ---------------------------------------------------------------------------

class SafetyGate:
    """Phase 3 — Risk-based approval gates, scope enforcement, and retry policy."""

    def classify_risk(self, task: dict) -> str:
        """Return the task's risk level.

        Uses the task's existing ``risk`` field if set and non-empty.
        Otherwise infers from keywords in the task description:
          - HIGH  : deploy, contract, blockchain, delete, remove, migration,
                    production, .env, keystore, password
          - MEDIUM: refactor, rewrite, restructure, security, rename, move
          - LOW   : everything else

        Args:
            task: Task dictionary, optionally containing ``risk`` and
                  ``description`` fields.

        Returns:
            "low", "medium", or "high".
        """
        existing = (task.get("risk") or "").strip().lower()
        if existing in ("low", "medium", "high"):
            return existing

        description = (task.get("description") or "").lower()
        for kw in _HIGH_KEYWORDS:
            if kw in description:
                logger.debug("classify_risk → high (matched keyword %r)", kw)
                return "high"
        for kw in _MEDIUM_KEYWORDS:
            if kw in description:
                logger.debug("classify_risk → medium (matched keyword %r)", kw)
                return "medium"
        return "low"

    async def check(
        self,
        task: dict,
        channel: discord.TextChannel,
        owner_id: int,
        bot: discord.Client,
    ) -> tuple[bool, str]:
        """Evaluate a task and return (approved, reason).

        Behaviour by risk level:

        - **LOW** : Auto-approved immediately (if SAFETY_AUTO_APPROVE_LOW is
          true), otherwise treated as MEDIUM.
        - **MEDIUM** : Posts a warning embed and auto-approves after
          SAFETY_MEDIUM_TIMEOUT_SECONDS unless the owner reacts ❌ or sends
          ``reject``/``no``/``cancel``.
        - **HIGH** : Posts a blocking embed and waits indefinitely (or until
          SAFETY_HIGH_TIMEOUT_SECONDS if > 0) for explicit owner approval.

        Args:
            task:     Task dictionary with at least a ``risk`` field.
            channel:  Discord text channel to post approval prompts into.
            owner_id: Discord user ID of the human owner.
            bot:      The discord.Client instance used for wait_for().

        Returns:
            (approved: bool, reason: str)
        """
        import discord as _discord

        risk = self.classify_risk(task)
        task_title = task.get("title") or task.get("description", "Unnamed task")[:80]

        logger.info("SafetyGate.check — task=%r risk=%s", task_title, risk)

        # ------------------------------------------------------------------ LOW
        if risk == "low":
            if AUTO_APPROVE_LOW:
                logger.info("Auto-approved (low risk): %r", task_title)
                return (True, "auto-approved: low risk")
            # fall through to medium handling
            risk = "medium"

        # --------------------------------------------------------------- MEDIUM
        if risk == "medium":
            timeout = MEDIUM_RISK_TIMEOUT
            embed = _discord.Embed(
                title="⚠️ Medium-risk task",
                description=(
                    f"**{task_title}**\n\n"
                    f"Auto-approving in **{timeout}s** unless you react ❌ or type `reject`."
                ),
                color=0xFFA500,
            )
            message = await channel.send(embed=embed)
            await message.add_reaction("✅")
            await message.add_reaction("❌")

            return await self._wait_for_decision(
                bot=bot,
                channel=channel,
                message=message,
                owner_id=owner_id,
                timeout=timeout,
                timeout_result=(True, "auto-approved: medium risk timeout"),
            )

        # ----------------------------------------------------------------- HIGH
        # risk == "high"
        timeout = HIGH_RISK_TIMEOUT if HIGH_RISK_TIMEOUT > 0 else None
        embed = _discord.Embed(
            title="🛑 High-risk task — requires explicit approval",
            description=(
                f"**{task_title}**\n\n"
                "React ✅ or type `approve` to proceed. "
                "This will **not** auto-approve."
            ),
            color=0xFF0000,
        )
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")

        if timeout is None:
            # Wait indefinitely — no timeout_result path
            return await self._wait_for_decision(
                bot=bot,
                channel=channel,
                message=message,
                owner_id=owner_id,
                timeout=None,
                timeout_result=(False, "timed out waiting for approval"),
            )
        else:
            return await self._wait_for_decision(
                bot=bot,
                channel=channel,
                message=message,
                owner_id=owner_id,
                timeout=timeout,
                timeout_result=(False, "timed out waiting for approval"),
            )

    # ---------------------------------------------------------------------- helpers

    async def _wait_for_decision(
        self,
        bot: discord.Client,
        channel: discord.TextChannel,
        message: discord.Message,
        owner_id: int,
        timeout: float | None,
        timeout_result: tuple[bool, str],
    ) -> tuple[bool, str]:
        """Listen for owner approval/rejection via reaction or message.

        Returns as soon as the owner reacts or messages, or when *timeout*
        expires (returning *timeout_result*).  If *timeout* is ``None`` the
        call blocks indefinitely until an explicit decision is received.
        """
        import discord as _discord

        _APPROVE_WORDS = {"approve", "yes"}
        _REJECT_WORDS = {"reject", "no", "cancel"}

        def reaction_check(reaction: discord.Reaction, user: discord.User) -> bool:
            return (
                user.id == owner_id
                and reaction.message.id == message.id
                and str(reaction.emoji) in ("✅", "❌")
            )

        def message_check(msg: discord.Message) -> bool:
            return (
                msg.author.id == owner_id
                and msg.channel.id == channel.id
                and msg.content.strip().lower() in (_APPROVE_WORDS | _REJECT_WORDS)
            )

        reaction_task = asyncio.ensure_future(
            bot.wait_for("reaction_add", check=reaction_check)
        )
        message_task = asyncio.ensure_future(
            bot.wait_for("message", check=message_check)
        )

        pending = {reaction_task, message_task}
        try:
            done, pending_remaining = await asyncio.wait(
                pending,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except Exception:
            reaction_task.cancel()
            message_task.cancel()
            return timeout_result

        # Cancel whichever task didn't fire
        for t in pending_remaining:
            t.cancel()

        if not done:
            # Timeout expired with no response
            logger.info("Decision timeout expired — returning %r", timeout_result)
            return timeout_result

        completed = done.pop()

        try:
            result = completed.result()
        except Exception as exc:
            logger.warning("Decision task raised: %s", exc)
            return (False, f"error waiting for decision: {exc}")

        # Reaction result is (Reaction, User); message result is Message
        if isinstance(result, tuple):
            reaction, _user = result
            if str(reaction.emoji) == "✅":
                logger.info("Owner approved via ✅ reaction")
                return (True, "human approved")
            else:
                logger.info("Owner rejected via ❌ reaction")
                return (False, "human rejected")
        else:
            word = result.content.strip().lower()
            if word in _APPROVE_WORDS:
                logger.info("Owner approved via message %r", word)
                return (True, "human approved")
            else:
                logger.info("Owner rejected via message %r", word)
                return (False, "human rejected")


# ---------------------------------------------------------------------------
# ScopeEnforcer
# ---------------------------------------------------------------------------

class ScopeEnforcer:
    """Verify that a file path falls within the declared scope of a task."""

    def check_scope(self, task: dict, target_path: str) -> tuple[bool, str]:
        """Return (in_scope, reason) for *target_path* against *task*.

        Scope enforcement is opt-in: if ``affected_files`` is absent or empty
        the check always passes.

        Match rules (checked in order for each entry in ``affected_files``):

        1. **Exact match** — entry equals ``target_path``.
        2. **Directory match** — entry ends with ``/`` and ``target_path``
           starts with that entry.

        Args:
            task:        Task dictionary, optionally containing an
                         ``affected_files`` list of strings.
            target_path: Absolute (or relative) path of the file being
                         modified.

        Returns:
            (True, "no scope declared")  if affected_files is empty/absent.
            (True, "in scope")           if target_path matches an entry.
            (False, "out of scope: …")   otherwise.
        """
        affected: list[str] = task.get("affected_files") or []
        if not affected:
            return (True, "no scope declared")

        for entry in affected:
            if entry.endswith("/"):
                if target_path.startswith(entry):
                    logger.debug("check_scope: %r matches directory %r", target_path, entry)
                    return (True, "in scope")
            else:
                if target_path == entry:
                    logger.debug("check_scope: %r exact match %r", target_path, entry)
                    return (True, "in scope")

        logger.warning(
            "check_scope: %r not in affected_files %r", target_path, affected
        )
        return (False, f"out of scope: {target_path} not in {affected}")


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

class RetryPolicy:
    """Execute a task function with automatic retry on failure."""

    async def execute_with_retry(
        self,
        execute_fn: Callable[[dict], Any],
        task: dict,
        max_retries: int = MAX_RETRIES,
    ) -> dict:
        """Call *execute_fn(task)* and retry up to *max_retries* times on failure.

        On each retry the task description is temporarily augmented with a
        note about the previous failure so the executor can try a different
        approach.  The original description is restored after each call.

        Args:
            execute_fn:   Async or sync callable that accepts a task dict and
                          returns a dict with at minimum ``success`` (bool) and
                          ``error`` (str) keys.
            task:         Task dictionary; must contain a ``description`` key.
            max_retries:  Maximum number of retry attempts (default 2, giving
                          up to 3 total attempts).

        Returns:
            The result dict from the last execution (successful or not).
        """
        original_description: str = task.get("description", "")
        result: dict = {}

        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(execute_fn):
                    result = await execute_fn(task)
                else:
                    result = execute_fn(task)
            except Exception as exc:
                logger.exception("execute_fn raised on attempt %d: %s", attempt + 1, exc)
                result = {"success": False, "error": str(exc)}
            finally:
                # Always restore the original description after the call
                task["description"] = original_description

            if result.get("success"):
                logger.info("execute_with_retry: succeeded on attempt %d", attempt + 1)
                return result

            if attempt < max_retries:
                error_msg = result.get("error", "unknown error")
                retry_n = attempt + 1
                logger.warning(
                    "Attempt %d/%d failed: %s — retrying",
                    retry_n,
                    max_retries + 1,
                    error_msg,
                )
                task["description"] = (
                    original_description
                    + f"\n\n[RETRY {retry_n}/{max_retries}] Previous attempt failed with "
                    f"error: {error_msg}. Try a different approach."
                )
            else:
                logger.error(
                    "execute_with_retry: all %d attempts exhausted", max_retries + 1
                )

        return result
