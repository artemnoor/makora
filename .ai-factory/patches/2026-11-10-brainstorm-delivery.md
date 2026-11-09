# Recover an interactive idea chat before documents exist

**Date:** 2026-11-10
**Files:** makora_core/preparation.py, tests/test_preparation.py
**Severity:** high

## Problem

The brainstorm screen stayed on chat confirmation after uncertain creation delivery. The chat had already asked the user for their idea, but the screen had no chat link.

## Root Cause

Recovery required result.json before discovering an unknown thread. Interactive brainstorming intentionally has no final result until the user discusses and approves their idea, creating a circular wait.

## Solution

Allow read-only discovery for user_idea sessions without a result file. Preserve the exact task path, completed turn, final reply and unique-match checks. Recovered sessions enter awaiting_idea with a usable chat identity; no documents are published or prompts resent.

## Prevention

Test recovery after restart before result.json exists, separately from document-producing stages. Delivery confirmation and artifact publication have different prerequisites.
