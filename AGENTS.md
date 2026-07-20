# Incident Memory Log

This file tracks previously resolved incidents.

## Incident: n_plus_one
- **Date**: 2026-07-20 19:27:10 UTC
- **Root Cause**: The N+1 query issue is caused by the get_orders function fetching a list of orders and then iterating over each order to fetch its associated items using the get_items_for_order function, resulting in a separate database query for each order.
- **Fix**: Optimize the queries to use a single query that fetches all the necessary data, such as using a JOIN or a subquery to fetch the order items in a single database call.
- **Confidence**: High
- **Summary**: The GET /orders endpoint is returning 500 errors due to a suspected N+1 query timeout, causing the database connection pool to overflow and resulting in a significant increase in latency and error rate.
---

## Incident: n_plus_one
- **Date**: 2026-07-20 19:28:47 UTC
- **Root Cause**: The n_plus_one bug, which was introduced in a recent deploy, caused the application to execute multiple separate SELECT queries for items with different order IDs, leading to a connection pool exhaustion
- **Fix**: Apply the patch from the Patch Writer, which fixes the n_plus_one bug in breakomatic/bugs/n_plus_one.py and includes a regression test in evals/test_regression.py
- **Confidence**: High
- **Summary**: The GET /orders endpoint was returning 500 errors due to a suspected N+1 query timeout, causing a high error rate and increased latency
---

## Incident: n_plus_one
- **Date**: 2026-07-20 19:30:57 UTC
- **Root Cause**: The N+1 query bug in the breakomatic/bugs/n_plus_one.py file, which was introduced in a recent deploy (sha: abc123f) and caused the database connection pool to become exhausted
- **Fix**: The patch writer fix, which involves updating the breakomatic/bugs/n_plus_one.py file to fix the N+1 query bug, as verified by the regression test evals/test_regression.py
- **Confidence**: High
- **Summary**: The GET /orders endpoint was returning 500 errors due to a suspected N+1 query timeout, resulting in a high error rate and increased latency
---
