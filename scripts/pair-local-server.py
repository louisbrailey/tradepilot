"""Create private TLS and iPhone pairing files. Run with the backend virtualenv."""
import argparse,base64,datetime,ipaddress,json,os,re,secrets
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
p=argparse.ArgumentParser()
p.add_argument('--private-dir',required=True)
p.add_argument('--address',required=True)
p.add_argument('--hostname',help='Optional stable mDNS hostname, such as My-Mac.local')
a=p.parse_args()
ip=ipaddress.ip_address(a.address)
if not ip.is_private: raise SystemExit('Use a private local-network address.')
if a.hostname and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.local', a.hostname):
 raise SystemExit('Use a single-label .local hostname.')
os.umask(0o077)
root=Path(a.private_dir).resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
configfile=root/'config.json'
config=json.loads(configfile.read_text()) if configfile.exists() else {}
config.setdefault('APP_ACCESS_TOKEN',secrets.token_urlsafe(48))
config.setdefault('WEBULL_LIVE_TRADING','disabled')
config.setdefault('TRADEPILOT_RUNTIME',str(root/'runtime'))
configfile.write_text(json.dumps(config,indent=2));configfile.chmod(0o600)
keyfile,certfile=root/'server.key',root/'server.pem'
if keyfile.exists() or certfile.exists():
 raise SystemExit('TLS files already exist. Preserve them; re-pair deliberately if the address changes.')
key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'TradePilot private gateway')])
now=datetime.datetime.now(datetime.timezone.utc)
cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
 .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5))
 .not_valid_after(now+datetime.timedelta(days=90))
 .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip)] + ([x509.DNSName(a.hostname)] if a.hostname else [])),critical=False)
 .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
 .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
 .sign(key,hashes.SHA256()))
keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
host=a.hostname or ('['+a.address+']' if ip.version == 6 else a.address)
pair={'endpoint':'https://'+host+':8787','token':config['APP_ACCESS_TOKEN'],
 'certificate':base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()}
(root/'TradePilotPairing.json').write_text(json.dumps(pair))
print('Created private TLS and device-pairing files. Keep the directory outside source archives.')
