# GitHub Copilot Instructions for Micro Trading Robot

## Core Behavior Rules

### Documentation Generation
- **DO NOT** create or generate documentation files (*.md) unless explicitly requested by the user
- **DO NOT** write summary documents, overview files, or README updates automatically
- **DO NOT** create step-by-step guides or checklists unless asked
- If documentation is needed, ask the user for permission first

### Code Implementation
- Focus on implementing functionality, not documenting it
- Generate code that is self-explanatory where possible
- Use inline comments only for complex logic
- Do implement docstrings for public functions and classes

### When User Says "Create", "Build", or "Implement"
- Assume they want code implementation, not documentation
- Do NOT automatically generate accompanying documentation
- Ask before creating documentation files

### When User Says "Test" or "Verify"
- Run tests and report results
- Do NOT create test documentation or reports automatically
- Report findings in console output, not markdown files

### When User Says "Deploy", "Start", or "Run"
- Execute the requested action
- Log output to console
- Do NOT create deployment guides or logs as markdown files

## Communication Style

### Keep Responses Brief
- 1-3 sentences for simple operations
- Longer responses only when needed to explain complexity
- Use bullet points for lists
- Avoid unnecessary elaboration

### Avoid Documentation in Responses
- Don't say "I've created a comprehensive guide..."
- Don't describe features across multiple markdown files
- Don't summarize work in document form unless asked
- Respond with facts about what was implemented

## Exceptions (When to Generate Documentation)

Documentation should be created ONLY when user explicitly asks for:
- "Create a README"
- "Write documentation for..."
- "Generate a guide for..."
- "Document the..."
- "Create a summary of..."
- "Write instructions for..."

## Examples

### ❌ WRONG
User: "Can you implement Trading212 integration?"
Response: "I've created comprehensive documentation including TRADING212_README.md, TRADING212_QUICKSTART.md, TRADING212_ARCHITECTURE.md..."

### ✅ RIGHT
User: "Can you implement Trading212 integration?"
Response: "✅ Trading212 integration complete. Created bot/trading212_api.py (302 lines) and bot/trading212_broker.py (320 lines). Dashboard integrated. Tests passing."

### ❌ WRONG
User: "Test the integration"
Response: "Created TRADING212_TEST_RESULTS.md with comprehensive test report..."

### ✅ RIGHT
User: "Test the integration"
Response: "✅ All tests passed: Account retrieval, BUY order creation (Order ID 703626), SELL order creation (Order ID 760326), P&L calculation (+$1.50), position tracking verified."

## File Management

- Move/delete/organize files as needed without creating documentation about it
- Use terminal commands directly for file operations
- Don't create index or manifest files unless asked

## Configuration & Setup

- Implement configuration changes directly
- Log implementation to console
- Don't create setup guides automatically
- Ask user if they want instructions documented

## Summary

**Primary rule: Code and action over documentation. Silence is golden.**

Only generate documentation files when explicitly requested. Everything else should be implemented with minimal explanation.
