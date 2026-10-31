"""Ephemeral test PKI; private keys are generated locally and never committed."""
import datetime as dt
import ipaddress
import json
from pathlib import Path
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def generate(directory, device_uuid=None):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ThirdHand ephemeral test CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    (root / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for label in ("server", "device", "unknown"):
        key = ec.generate_private_key(ec.SECP256R1()) if label == "server" else ed25519.Ed25519PrivateKey.generate()
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(hours=1)).not_valid_after(now + dt.timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if label == "server" else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False))
        if label == "server":
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        elif label == "device" and device_uuid:
            builder = builder.add_extension(x509.SubjectAlternativeName([
                x509.UniformResourceIdentifier('urn:thirdhand:probe:' + device_uuid)]), critical=False)
        cert = builder.sign(ca_key, hashes.SHA256())
        (root / f"{label}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root / f"{label}.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (root / f"{label}.key").chmod(0o600)


if __name__ == "__main__":
    generate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps({"generated": True}))
