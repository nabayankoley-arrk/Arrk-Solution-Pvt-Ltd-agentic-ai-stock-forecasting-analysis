"""Postgres access for the backend.

connection.get_connection() is the shared entry point, matching what the agent
packages already import. documents.py holds the reads and writes for the
document summarisation job; schema.sql defines its one table.
"""
