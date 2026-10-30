// Adapter for existing keyring-only role keys. Reuse the pinned helper's proof
// domains; private material is passed through stdin and is never logged/saved.
import {ProxySignature} from './bin/structs-sign-proxy.js';
import {Secp256k1, sha256, ripemd160} from '@cosmjs/crypto';
import {toBech32, fromHex} from '@cosmjs/encoding';

let privateKey;
try {
    let size = 0;
    const chunks = [];
    for await (const chunk of process.stdin) {
        size += chunk.length;
        if (size > 4096) throw new Error('input limit');
        chunks.push(chunk);
    }
    const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (typeof input.private_key !== 'string' || !/^[0-9a-fA-F]{64}$/.test(input.private_key)) throw new Error('key encoding');
    privateKey = fromHex(input.private_key);
    const pair = await Secp256k1.makeKeypair(privateKey);
    const pubkey = Secp256k1.compressPubkey(pair.pubkey);
    const address = toBech32('structs', ripemd160(sha256(pubkey)));
    if (address !== input.address) throw new Error('identity mismatch');
    const proof = new ProxySignature();
    Object.assign(proof, {signatureType: 'guild-join', guildId: input.guild_id, nonce: input.nonce,
                          address, account: {pubkey, privkey: privateKey}});
    proof.getMessage();
    proof.getDigest();
    await proof.getSignature();
    process.stdout.write(proof.getOutput() + '\n');
} catch {
    process.stderr.write('Unable to sign the requested keyring proof\n');
    process.exitCode = 1;
} finally {
    if (privateKey) privateKey.fill(0);
}
