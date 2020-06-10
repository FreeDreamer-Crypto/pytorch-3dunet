import torch

from pytorch3dunet.unet3d.utils import expand_as_one_hot


def _compute_cluster_means(emb, tar, c_mean_fn):
    instances = torch.unique(tar)
    C = instances.size(0)

    single_target = expand_as_one_hot(tar.unsqueeze(0), C).squeeze(0)
    single_target = single_target.unsqueeze(1)
    spatial_dims = emb.dim() - 1

    cluster_means, _, _ = c_mean_fn(emb, single_target, spatial_dims)
    return cluster_means


def _extract_instance_masks(embeddings, target, c_mean_fn, dist_to_mask_fn, combine_masks):
    def _add_noise(mask, sigma=0.05):
        gaussian_noise = torch.randn(mask.size()).to(mask.device) * sigma
        mask += gaussian_noise
        return mask

    # iterate over batch
    real_masks = []
    fake_masks = []

    for emb, tar in zip(embeddings, target):
        cluster_means = _compute_cluster_means(emb, tar, c_mean_fn)
        rms = []
        fms = []
        for i, cm in enumerate(cluster_means):
            if i == 0:
                # ignore 0-label
                continue

            # compute distance map; embeddings is ExSPATIAL, cluster_mean is ExSINGLETON_SPATIAL, so we can just broadcast
            dist_to_mean = torch.norm(emb - cm, 'fro', dim=0)
            # convert distance map to instance pmaps
            inst_pmap = dist_to_mask_fn(dist_to_mean)
            # add channel dim
            fms.append(inst_pmap.unsqueeze(0))

            assert i in target
            inst_mask = (tar == i).float()
            # add noise to instance mask to prevent discriminator from converging too quickly
            inst_mask = _add_noise(inst_mask)
            # clamp values
            inst_mask.clamp_(0, 1)
            rms.append(inst_mask.unsqueeze(0))

        if combine_masks and len(fms) > 0:
            fake_mask = torch.zeros_like(fms[0])
            for fm in fms:
                fake_mask += fm

            real_mask = (tar > 0).float()
            real_mask = real_mask.unsqueeze(0)
            real_mask = _add_noise(real_mask)
            real_mask.clamp_(0, 1)

            real_masks.append(real_mask)
            fake_masks.append(fake_mask)
        else:
            real_masks.extend(rms)
            fake_masks.extend(fms)

    if len(real_masks) == 0:
        return None, None

    real_masks = torch.stack(real_masks).to(embeddings.device)
    fake_masks = torch.stack(fake_masks).to(embeddings.device)
    return real_masks, fake_masks
