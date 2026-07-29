"""SEC EDGAR diligence tooling for a private-equity deal team.

Two layers, deliberately separated:

  edgar_client — ALL logic. Fetch, parse, normalise, source-attribute, compute,
                 judge meaningfulness, raise flags. Importable and testable
                 without the MCP protocol, which is what keeps the test suite
                 offline and fast.
  server       — a thin MCP shim. Registers the client's functions as tools and
                 does nothing else. No logic belongs here.

The design thesis: code computes, the model narrates. Ratios, whether a ratio is
*meaningful*, and every red flag are decided in Python against fixed thresholds,
so two analysts running the same screen get byte-identical flags — a property a
prompt cannot have.
"""

__version__ = "1.0.0"

__all__ = ["edgar_client", "server", "__version__"]
