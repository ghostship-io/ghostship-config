{
  description = "Placeholder for the private agent source. The real source is supplied out of band, never from this repository.";

  # The private source declares the same input as this placeholder, so the
  # committed lock keeps one node for it and the substitution is a change of
  # the locked source alone. The declaration is identical, so the lock keeps
  # the same pinned revision for it in either state.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

  outputs = { self, nixpkgs }:
    let
      notSupplied = throw ''
        The private agent source was not supplied.

        This repository names no private repository, revision, or content hash.
        The pinned source is supplied from a specification that is private to
        continuous integration and to the deployment host, and it is applied
        before the evaluation that needs it. See
        docs/agent-revision-pinning.md for the procedure.
      '';
    in
    {
      # Every output the deployment consumes is deliberately absent. An
      # evaluation that reaches this point needs the real source.
      packages = notSupplied;
      lib = notSupplied;
      overlays = notSupplied;
      apps = notSupplied;
    };
}
