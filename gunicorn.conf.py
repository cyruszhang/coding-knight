def post_fork(server, worker):
    # Run schema init/seeding here, not at module import time: gunicorn's
    # master process imports app.py once (to validate it) before forking
    # workers. If that import touched libsql's Rust/tokio runtime, every
    # forked worker would inherit a broken copy of it and hang on first
    # query. post_fork runs after this worker's own fork, so it's safe.
    from app import init_db
    init_db()
