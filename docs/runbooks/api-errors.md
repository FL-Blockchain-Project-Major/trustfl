# API errors

1. Check `trustfl_api_errors_total` by route and status.
2. Compare the error window with deployment and database/Redis events.
3. Use the `X-Request-ID` and `Traceparent` values from a failing response to
   correlate application logs.
4. Roll back only if the error is deployment-correlated; otherwise isolate the
   failing dependency and preserve the request evidence.
