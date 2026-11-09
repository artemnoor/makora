# Recover completed preparation after uncertain creation delivery

**Date:** 2026-11-10
**Files:** makora_core/preparation.py, makora_core/agents/runtime.py, tests/test_preparation.py
**Severity:** high

## Problem

A Desktop creation timeout left the stage unconfirmed despite a completed chat and an existing result.json. Rechecking could not recover it, because neither the stage nor its chat group retained a thread ID.

## Root Cause

Creation can succeed before the transport returns its identifiers. Recovery previously required a known thread ID, and the exception handler also discarded identifiers supplied in delivery-error details.

## Solution

Retain available thread/turn IDs before validating delivery and from DELIVERY_UNKNOWN details. For a completed result without any chat identity, inspect a bounded read-only catalog filtered to the exact project directory. Accept only one completed turn containing the exact session TASK.json path and a final assistant message. Persist the recovered chat association and pass the result through all ordinary artifact and evidence checks. Never resend the prompt or auto-approve the stage.

## Prevention

Exercise creation errors without IDs, partial error IDs, unrelated history, ambiguous matching threads and unfinished turns. A result file alone cannot prove which session completed. Recheck recovery after restart as well as ordinary accepted operations.
